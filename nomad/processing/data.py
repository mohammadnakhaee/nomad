#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

'''
This module comprises a set of persistent document classes that hold all user related
data. These are information about users, their uploads and datasets, the associated
calculations, and files


.. autoclass:: Calc

.. autoclass:: Upload

'''

from typing import cast, Any, List, Tuple, Set, Iterator, Dict, Iterable, Sequence, Union
from mongoengine import (
    StringField, DateTimeField, BooleanField, IntField, ListField)
from pymongo import UpdateOne
from structlog import wrap_logger
from contextlib import contextmanager
import copy
import os.path
from datetime import datetime, timedelta
import hashlib
from structlog.processors import StackInfoRenderer, format_exc_info, TimeStamper
import yaml
import json
from functools import lru_cache
import requests
from fastapi.exceptions import RequestValidationError
from pydantic.error_wrappers import ErrorWrapper

from nomad import utils, config, infrastructure, search, datamodel, metainfo, parsing, client
from nomad.files import (
    PathObject, UploadFiles, PublicUploadFiles, StagingUploadFiles, UploadBundle, create_tmp_dir)
from nomad.processing.base import (
    Proc, process, ProcessStatus, ProcessFailure, ProcessAlreadyRunning)
from nomad.parsing import Parser
from nomad.parsing.parsers import parser_dict, match_parser
from nomad.normalizing import normalizers
from nomad.datamodel import (
    EntryArchive, EntryMetadata, MongoUploadMetadata, MongoEntryMetadata, MongoSystemMetadata,
    EditableUserMetadata, UploadMetadata, AuthLevel)
from nomad.archive import (
    write_partial_archive_to_mongo, delete_partial_archives_from_mongo)
from nomad.app.v1.models import (
    MetadataEditRequest, And, Aggregation, TermsAggregation, MetadataPagination, MetadataRequired)
from nomad.search import update_metadata as es_update_metadata

section_metadata = datamodel.EntryArchive.metadata.name
section_workflow = datamodel.EntryArchive.workflow.name
section_results = datamodel.EntryArchive.results.name


_mongo_upload_metadata = tuple(
    quantity.name for quantity in MongoUploadMetadata.m_def.definitions)
_mongo_entry_metadata = tuple(
    quantity.name for quantity in MongoEntryMetadata.m_def.definitions)
_mongo_system_metadata = tuple(
    quantity.name for quantity in MongoSystemMetadata.m_def.definitions)
_mongo_entry_metadata_except_system_fields = tuple(
    quantity_name for quantity_name in _mongo_entry_metadata
    if quantity_name not in _mongo_system_metadata)
_editable_metadata: Dict[str, metainfo.Definition] = {
    quantity.name: quantity for quantity in EditableUserMetadata.m_def.definitions
    if isinstance(quantity, metainfo.Quantity)}


def _pack_log_event(logger, method_name, event_dict):
    try:
        log_data = dict(event_dict)
        log_data.update(**{
            key: value
            for key, value in getattr(logger, '_context', {}).items()
            if key not in ['service', 'release', 'upload_id', 'calc_id', 'mainfile', 'process_status']})
        log_data.update(logger=logger.name)

        return log_data
    except Exception:
        # raising an exception would cause an indefinite loop
        return event_dict


_log_processors = [
    StackInfoRenderer(),
    _pack_log_event,
    format_exc_info,
    TimeStamper(fmt="%Y-%m-%d %H:%M.%S", utc=False)]


def check_user_ids(user_ids: Iterable[str], error_message: str):
    '''
    Checks if all user_ids provided in the Iterable `user_ids` are valid. If not, raises an
    AssertionError with the specified error message. The string {id} in `error_message` is
    replaced with the bad value.
    '''
    for user_id in user_ids:
        user = datamodel.User.get(user_id=user_id)
        assert user is not None, error_message.replace('{id}', user_id)


def keys_exist(data: Dict[str, Any], required_keys: Iterable[str], error_message: str):
    '''
    Checks if the specified keys exist in the provided dictionary structure `data`.
    Supports dot-notation to access subkeys.
    '''
    for key in required_keys:
        current = data
        for sub_key in key.split('.'):
            assert sub_key in current, error_message.replace('{key}', key)
            current = current[sub_key]


def generate_entry_id(upload_id: str, mainfile: str) -> str:
    '''
    Generates an id for an entry.
    Arguments:
        upload_id: The id of the upload
        mainfile: The mainfile path (relative to the raw directory).
    Returns:
        The generated entry id
    '''
    return utils.hash(upload_id, mainfile)


class MetadataEditRequestHandler:
    '''
    Class for handling a request to edit metadata. The request may originate either from
    metadata files in the raw directory or from a json dictionary complying with the
    :class:`MetadataEditRequest` format. If the edit request is limited to a specific upload,
    `upload_id` should be specified (only when this is the case can upload level metadata be edited).
    '''
    @classmethod
    def edit_metadata(
            cls, edit_request_json: Dict[str, Any], upload_id: str,
            user: datamodel.User) -> Dict[str, Any]:
        '''
        Method to verify and execute a generic request to edit metadata from a certain user.
        The request is specified as a json dictionary. Optionally, the request could be restricted
        to a single upload by specifying `upload_id` (this is necessary when editing upload
        level attributes). If `edit_request_json` has `verify_only` set to True, only
        verification is carried out (i.e. nothing is actually updated). To just run the
        verification should be quick in comparison to actually executing the request (which
        may take some time and requires one or more @process to finish). If the request passes
        the verification step and `verify_only` is not set to True, we will send the request
        for execution, by initiating the @process :func:`edit_upload_metadata` for each affected
        upload.

        The method returns a json dictionary with verified data (references resolved to explicit
        IDs, list actions always expressed as dicts with "op" and "values", etc), or raises
        an exception, namely:
         -  A :class:`ValidationError` if the request json can't be parsed by pydantic
         -  A :class:`RequestValidationError` with information about validation failures and
            their location (most errors should be of this type, provided that the json is valid)
         -  A :class:`ProcessAlreadyRunning` exception if one of the affected uploads has
            a running process
         -  Some other type of exception, if something goes wrong unexpectedly (should hopefully
            never happen)
        '''
        logger = utils.get_logger('nomad.processing.edit_metadata')
        handler = MetadataEditRequestHandler(
            logger, user, edit_request_json=edit_request_json, upload_id=upload_id)
        # Validate the request
        handler.validate_request()  # Should raise errors if something looks wrong

        if not edit_request_json.get('verify_only'):
            # Check if any of the affected uploads are processing
            for upload in handler.affected_uploads:
                upload.reload()
                if upload.process_running:
                    raise ProcessAlreadyRunning(f'Upload {upload.upload_id} is currently processing')
            # Looks good, try to trigger processing
            for upload in handler.affected_uploads:
                upload.edit_upload_metadata(edit_request_json, user.user_id)  # Trigger the process
        # All went well, return a verified json as response
        verified_json = copy.deepcopy(handler.edit_request_json)
        verified_json['metadata'] = handler.root_metadata
        verified_json['entries'] = handler.entries_metadata
        return verified_json

    def __init__(
            self, logger, user: datamodel.User,
            edit_request_json: Dict[str, Any] = None,
            upload_files: StagingUploadFiles = None,
            upload_id: str = None):
        # Initialization
        assert user, 'Must specify `user`'
        assert (edit_request_json is None) != (upload_files is None), (
            'Must specify either `edit_request` or `upload_files`')
        self.logger = logger
        self.user = user
        self.edit_request_json = edit_request_json
        self.upload_files = upload_files
        self.upload_id = upload_id

        self.errors: List[ErrorWrapper] = []  # A list of all encountered errors, if any
        self.edit_attempt_locs: List[Tuple[str, ...]] = []  # locs where user has attempted to edit something
        self.required_auth_level = AuthLevel.none  # Maximum required auth level for the edit
        self.required_auth_level_locs: List[Tuple[str, ...]] = []  # locs where maximal auth level is needed
        self.encountered_users: Dict[str, str] = {}  # { ref: user_id | None }, ref = user_id | username | email
        self.encountered_datasets: Dict[str, datamodel.Dataset] = {}  # { ref : dataset | None }, ref = dataset_id | dataset_name
        self.root_metadata: Dict[str, Any] = None  # The metadata specified at the top/root level

        # Specific to the MetadataEditRequest case
        self.edit_request: MetadataEditRequest = None
        self.affected_uploads: List['Upload'] = None  # A MetadataEditRequest may involve multiple uploads
        self.entries_metadata: Dict[str, Dict[str, Any]] = {}  # Metadata specified for individual entries

    def validate_metadata_files(self):
        pass  # TODO

    def validate_request(self):
        ''' Validates the provided edit_request_json. '''
        # Validate the request json. Will raise ValidationError if json is malformed
        self.edit_request = MetadataEditRequest(**self.edit_request_json)
        try:
            if not self.upload_id and not self.edit_request.query:
                return self._loc_error('Must specify `query`', 'query')
            if self.edit_request.entries and not self.edit_request.entries_key:
                return self._loc_error('Must specify `entries_key` when specifying `entries`', 'entries_key')

            can_edit_upload_fields = bool(self.upload_id and not self.edit_request.query)
            if self.edit_request.metadata:
                self.root_metadata = self._verify_metadata_edit_actions(
                    self.edit_request_json['metadata'], ('metadata',), can_edit_upload_fields)
            if self.edit_request.entries:
                for key, entry_metadata in self.edit_request_json['entries'].items():
                    verified_metadata = self._verify_metadata_edit_actions(
                        entry_metadata, ('entries', key), False)
                    self.entries_metadata[key] = verified_metadata

            if not self.edit_attempt_locs:
                return self._loc_error('No fields to update specified', 'metadata')
            if self.required_auth_level == AuthLevel.admin and not self.user.is_admin:
                for loc in self.required_auth_level_locs:
                    self._loc_error('Admin rights required', loc)
                return

            embargo_length: int = self.root_metadata.get('embargo_length')
            try:
                self.affected_uploads = self._find_request_uploads()
            except Exception as e:
                return self._loc_error('Could not evaluate query: ' + str(e), 'query')
            if not self.affected_uploads:
                if self.edit_request.query:
                    return self._loc_error('No matching entries found', 'query')
                return self._loc_error('No matching upload found', 'upload_id')
            for upload in self.affected_uploads:
                # Check permissions
                coauthor = upload.coauthors and self.user.user_id in upload.coauthors
                main_author = self.user.user_id == upload.main_author
                admin = self.user.is_admin
                if self.required_auth_level == AuthLevel.coauthor:
                    has_access = coauthor or main_author or admin
                elif self.required_auth_level == AuthLevel.main_author:
                    has_access = main_author or admin
                elif self.required_auth_level == AuthLevel.admin:
                    has_access = admin
                else:
                    assert False, 'Invalid required_auth_level'  # Should not happen
                if not has_access:
                    for loc in self.required_auth_level_locs:
                        self._loc_error(
                            f'{self.required_auth_level} access required for upload '
                            f'{upload.upload_id}', loc)
                    return
                # Other checks
                if embargo_length is not None:
                    if upload.published and not admin and embargo_length != 0:
                        self._loc_error(
                            f'Upload {upload.upload_id} is published, embargo can only be lifted',
                            ('metadata', 'embargo_length'))
                if upload.published and not admin:
                    has_invalid_edit = False
                    for edit_loc in self.edit_attempt_locs:
                        if edit_loc[-1] not in ('embargo_length', 'datasets'):
                            has_invalid_edit = True
                            self._loc_error(
                                f'Cannot update, upload {upload.upload_id} is published.', edit_loc)
                    if has_invalid_edit:
                        return
        except Exception as e:
            # Something unexpected has gone wrong
            self.logger.error(e)
            raise
        finally:
            if self.errors:
                raise RequestValidationError(errors=self.errors)

    def get_upload_metadata_to_set(self, upload: 'Upload') -> Dict[str, Any]:
        '''
        Returns a dictionary with verified metadata to update on the Upload object. The
        values have the correct type for mongo. Assumes that the corresponding validation method
        (i.e. :func:`validate_metadata_files` or :func: `validate_request`) have been run.
        '''
        rv: Dict[str, Any] = {}
        if self.root_metadata:
            self._applied_mongo_actions(upload, self.root_metadata, rv)
        return rv

    def get_entry_metadata_to_set(self, upload: 'Upload', entry: 'Calc') -> Dict[str, Any]:
        '''
        Returns a dictionary with verified metadata to update on the entry object. The
        values have the correct type for mongo. Assumes that the corresponding validation method
        (i.e. :func:`validate_metadata_files` or :func: `validate_request`) have been run.
        '''
        rv: Dict[str, Any] = {}
        if self.root_metadata:
            self._applied_mongo_actions(entry, self.root_metadata, rv)
        if self.edit_request:
            # Source = edit_request
            if self.entries_metadata:
                entry_key = self._get_entry_key(entry, self.edit_request.entries_key)
                entry_metadata = self.entries_metadata.get(entry_key)
                if entry_metadata:
                    # We also have actions for this particular entry specified
                    self._applied_mongo_actions(entry, entry_metadata, rv)
        else:
            # Source = metadata files
            pass  # TODO
        return rv

    def _loc_error(self, msg: str, loc: Union[str, Tuple[str, ...]]):
        ''' Registers a located error. '''
        self.errors.append(ErrorWrapper(Exception(msg), loc=loc))
        self.logger.error(msg, loc=loc)

    def _verify_metadata_edit_actions(
            self, metadata_edit_actions: Dict[str, Any], loc: Tuple[str, ...],
            can_edit_upload_fields: bool, auth_level: AuthLevel = None) -> Dict[str, Any]:
        '''
        Performs *basic* validation of a dictionary with metadata edit actions, and returns a
        dictionary with the same structure, but containing only the *verified* actions. Verified
        actions are actions that pass validation. Moreover:
            1)  For actions on lists, the verified action value is always expressed as a
                list operation (a dictionary with `op` and `values`)
            2)  User references (which can be specified by a user_id, a username, or an email)
                are always converted to user_id
            3)  dataset references (which can be specified either by dataset_id or dataset_name)
                are always replaced with dataset_ids, and it is verified that none of the
                datasets has a doi.
            4)  Only `add` and `remove` operations are allowed for datasets.
        '''
        rv = {}
        for quantity_name, action in metadata_edit_actions.items():
            if action is not None:
                success, verified_action = self._verify_metadata_edit_action(
                    quantity_name, action, loc + (quantity_name,), can_edit_upload_fields, auth_level)
                if success:
                    rv[quantity_name] = verified_action
        return rv

    def _verify_metadata_edit_action(
            self, quantity_name: str, action: Any, loc: Tuple[str, ...],
            can_edit_upload_fields: bool, auth_level: AuthLevel) -> Tuple[bool, Any]:
        '''
        Performs basic validation of a single action. Returns (success, verified_action).
        '''
        definition = _editable_metadata.get(quantity_name)
        if not definition:
            self._loc_error('Unknown quantity', loc)
            return False, None

        self.edit_attempt_locs.append(loc)

        field_auth_level = getattr(definition, 'a_auth_level', AuthLevel.coauthor)

        if auth_level is not None:
            # Our auth level is known, check it immediately
            if field_auth_level > auth_level:
                self._loc_error(f'{field_auth_level} privileges required', loc)
                return False, None
        if field_auth_level > self.required_auth_level:
            self.required_auth_level = field_auth_level
            self.required_auth_level_locs = [loc]
        if quantity_name in _mongo_upload_metadata and not can_edit_upload_fields:
            self._loc_error('Quantity can only be edited on the upload level', loc)
            return False, None

        try:
            if definition.is_scalar:
                return True, self._verified_value(definition, action)
            else:
                # We have a non-scalar quantity
                if type(action) == dict:
                    # Action is a dict - expected to contain op and values
                    assert action.keys() == {'op', 'values'}, 'Expected keys `op` and `values`'
                    op = action['op']
                    values = action['values']
                    assert op in ('set', 'add', 'remove'), 'op should be `set`, `add` or `remove`'
                    if quantity_name == 'datasets' and op == 'set':
                        self._loc_error(
                            'Only `add` and `remove` operations permitted for datasets', loc)
                        return False, None
                else:
                    op = 'set'
                    values = action
                    if quantity_name == 'datasets':
                        op = 'add'  # Just specifying a list will be interpreted as add, rather than fail.
                values = values if type(values) == list else [values]
                verified_values = [self._verified_value(definition, v) for v in values]
                return True, dict(op=op, values=verified_values)
        except Exception as e:
            self._loc_error(str(e), loc)
            return False, None

    def _verified_value(
            self, definition: metainfo.Definition, value: Any) -> Any:
        '''
        Verifies a *singular* action value (i.e. for list quantities we should run this method
        for each value in the list, not with the list itself as input). Returns the verified
        value, which may be different from the origial value. It:
            1) ensures a return value of a primitive type (str, int, float, bool or None),
            2) that user refs exist,
            3) that datasets refs exist and do not have a doi.
            4) Translates user refs to user_id and dataset refs to dataset_id, if needed.
        Raises exception in case of failures.
        '''
        if definition.type in (str, int, float, bool):
            assert value is None or type(value) == definition.type, f'Expected a {definition.type.__name__}'
            if definition.name == 'embargo_length':
                assert 0 <= value <= 36, 'Value should be between 0 and 36'
            return None if value == '' else value
        elif definition.type == metainfo.Datetime:
            if value is not None:
                datetime.fromisoformat(value)  # Throws exception if badly formatted timestamp
            return None if value == '' else value
        elif isinstance(definition.type, metainfo.MEnum):
            assert type(value) == str, 'Expected a string value'
            if value == '':
                return None
            assert value in definition.type._values, f'Bad enum value {value}'
            return value
        elif isinstance(definition.type, metainfo.Reference):
            assert type(value) == str, 'Expected a string value'
            reference_type = definition.type.target_section_def.section_cls
            if reference_type in [datamodel.User, datamodel.Author]:
                if value in self.encountered_users:
                    user_id = self.encountered_users[value]
                else:
                    # New user reference encountered, try to fetch it
                    user_id = None
                    try:
                        user_id = datamodel.User.get(user_id=value).user_id
                    except KeyError:
                        try:
                            user_id = datamodel.User.get(username=value).user_id
                        except KeyError:
                            if '@' in value:
                                try:
                                    user_id = datamodel.User.get(email=value).user_id
                                except KeyError:
                                    pass
                    self.encountered_users[value] = user_id
                assert user_id is not None, f'User reference not found: `{value}`'
                return user_id
            elif reference_type == datamodel.Dataset:
                dataset = self._get_dataset(value)
                assert dataset is not None, f'Dataset reference not found: `{value}`'
                assert self.user.is_admin or dataset.user_id == self.user.user_id, (
                    f'Dataset `{value}` does not belong to you')
                assert not dataset.doi, f'Dataset `{value}` has a doi and cannot be changed'
                return dataset.dataset_id
        else:
            assert False, 'Unhandled value type'  # Should not happen

    def _applied_mongo_actions(
            self, mongo_doc: Union['Upload', 'Calc'],
            verified_actions: Dict[str, Any], applied_actions: Dict[str, Any]):
        '''
        Calculates the upload or entry level *applied actions*, i.e. key-value pairs with
        data to set on the provided `mongo_doc` in order to carry out the actions specified
        by `verified_actions`. The result is added to `applied_actions`.
        '''
        for quantity_name, verified_action in verified_actions.items():
            if isinstance(mongo_doc, Calc) and quantity_name not in _mongo_entry_metadata:
                continue
            elif isinstance(mongo_doc, Upload) and quantity_name not in _mongo_upload_metadata:
                continue
            applied_actions[quantity_name] = self._applied_mongo_action(
                mongo_doc, quantity_name, verified_action)

    def _applied_mongo_action(self, mongo_doc, quantity_name: str, verified_action: Any) -> Any:
        definition = _editable_metadata[quantity_name]
        if definition.is_scalar:
            if definition.type == metainfo.Datetime and verified_action:
                return datetime.fromisoformat(verified_action)
            return verified_action
        # Non-scalar property. The verified action should be a dict with op and values
        op, values = verified_action['op'], verified_action['values']
        old_list = getattr(mongo_doc, quantity_name, [])
        new_list = [] if op == 'set' else old_list.copy()
        for v in values:
            if op == 'add' or op == 'set':
                if v not in new_list:
                    if quantity_name in ('coauthors', 'reviewers') and v == mongo_doc.main_author:
                        continue  # Prevent adding the main author to coauthors or reviewers
                    new_list.append(v)
            elif op == 'remove':
                if v in new_list:
                    new_list.remove(v)
        return new_list

    def _get_entry_key(self, entry: 'Calc', entries_key: str) -> str:
        if entries_key == 'calc_id' or entries_key == 'entry_id':
            return entry.calc_id
        elif entries_key == 'mainfile':
            return entry.mainfile
        assert False, f'Invalid entries_key: {entries_key}'

    def _get_dataset(self, ref: str) -> datamodel.Dataset:
        '''
        Gets a dataset. They can be identified either using dataset_id or dataset_name, but
        only datasets belonging to the user can be specified using names. If no matching
        dataset can be found, None is returned.
        '''
        if ref in self.encountered_datasets:
            return self.encountered_datasets[ref]
        else:
            # First time we encounter this ref
            try:
                dataset = datamodel.Dataset.m_def.a_mongo.get(dataset_id=ref)
            except KeyError:
                try:
                    dataset = datamodel.Dataset.m_def.a_mongo.get(
                        user_id=self.user.user_id, dataset_name=ref)
                except KeyError:
                    dataset = None
            self.encountered_datasets[ref] = dataset
        return dataset

    def _restricted_request_query(self, upload_id: str = None):
        '''
        Gets the query of the request, if it has any. If we have a query and if an `upload_id`
        is specified, we return a modified query, by restricting the original query to this upload.
        '''
        query = self.edit_request.query
        if upload_id and query:
            # Restrict query to the specified upload
            return And(**{'and': [{'upload_id': upload_id}, query]})
        return query

    def _find_request_uploads(self) -> List['Upload']:
        ''' Returns a list of :class:`Upload`s matching the edit request. '''
        query = self._restricted_request_query(self.upload_id)
        if query:
            # Perform the search, aggregating by upload_id
            search_response = search.search(
                user_id=self.user.user_id,
                owner=self.edit_request.owner,
                query=query,
                aggregations=dict(agg=Aggregation(terms=TermsAggregation(quantity='upload_id'))),
                pagination=MetadataPagination(page_size=0))
            terms = search_response.aggregations['agg'].terms  # pylint: disable=no-member
            return [Upload.get(bucket.value) for bucket in terms.data]  # type: ignore
        elif self.upload_id:
            # Request just specifies an upload_id, no query
            try:
                return [Upload.get(self.upload_id)]
            except KeyError:
                pass
        return []

    def find_request_entries(self, upload: 'Upload') -> Iterable['Calc']:
        ''' Finds the entries of the specified upload which are effected by the request. '''
        query = self._restricted_request_query(upload.upload_id)
        if query:
            # We have a query. Execute it to get the entries.
            search_result = search.search_iterator(
                user_id=self.user.user_id,
                owner=self.edit_request.owner,
                query=query,
                required=MetadataRequired(include=['calc_id']))
            for result in search_result:
                yield Calc.get(result['calc_id'])
        else:
            # We have no query. Return all entries for the upload
            for entry in Calc.objects(upload_id=upload.upload_id):
                yield entry


class Calc(Proc):
    '''
    Instances of this class represent calculations. This class manages the elastic
    search index entry, files, and archive for the respective calculation.

    It also contains the calculations processing and its state.

    The attribute list, does not include the various metadata properties generated
    while parsing, including ``code_name``, ``code_version``, etc.

    Attributes:
        upload_id: the id of the upload to which this entry belongs
        calc_id: the calc_id of this calc
        calc_hash: the hash of the entry files
        entry_create_time: the date and time of the creation of the entry
        last_processing_time: the date and time of the last processing
        last_edit_time: the date and time the user metadata was last edited
        mainfile: the mainfile (including path in upload) that was used to create this calc
        parser_name: the name of the parser used to process this calc
        pid: the legacy NOMAD pid of the entry
        external_id: a user provided external id. Usually the id for an entry in an
            external database where the data was imported from
        nomad_version: the NOMAD version used for the last processing
        nomad_commit: the NOMAD commit used for the last processing
        comment: a user provided comment for this entry
        references: user provided references (URLs) for this entry
        entry_coauthors: a user provided list of co-authors specific for this entry. Note
            that normally, coauthors should be set on the upload level.
        datasets: a list of user curated datasets this entry belongs to
    '''
    upload_id = StringField(required=True)
    calc_id = StringField(primary_key=True)
    calc_hash = StringField()
    entry_create_time = DateTimeField(required=True)
    last_processing_time = DateTimeField()
    last_edit_time = DateTimeField()
    mainfile = StringField()
    parser_name = StringField()
    pid = StringField()
    external_id = StringField()
    nomad_version = StringField()
    nomad_commit = StringField()
    comment = StringField()
    references = ListField(StringField())
    entry_coauthors = ListField()
    datasets = ListField(StringField())

    meta: Any = {
        'strict': False,
        'indexes': [
            'upload_id',
            'parser_name',
            ('upload_id', 'mainfile'),
            ('upload_id', 'parser_name'),
            ('upload_id', 'process_status'),
            ('upload_id', 'nomad_version'),
            'process_status',
            'last_processing_time',
            'datasets',
            'pid'
        ]
    }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('entry_create_time', datetime.utcnow())
        super().__init__(*args, **kwargs)
        self._parser_results: EntryArchive = None
        self._is_initial_processing: bool = False
        self._upload: Upload = None
        self._upload_files: StagingUploadFiles = None
        self._calc_proc_logs: List[Any] = None

        self._entry_metadata: EntryMetadata = None
        self._perform_index = True

    @classmethod
    def get(cls, id) -> 'Calc':
        return cls.get_by_id(id, 'calc_id')

    @property
    def entry_id(self) -> str:
        ''' Just an alias for calc_id. '''
        return self.calc_id

    @property
    def mainfile_file(self) -> PathObject:
        return self.upload_files.raw_file_object(self.mainfile)

    @property
    def processed(self) -> bool:
        return self.process_status == ProcessStatus.SUCCESS

    @property
    def upload(self) -> 'Upload':
        if not self._upload:
            self._upload = Upload.get(self.upload_id)
            self._upload.worker_hostname = self.worker_hostname
        return self._upload

    def _initialize_metadata_for_processing(self):
        '''
        Initializes self._entry_metadata and self._parser_results in preparation for processing.
        Existing values in mongo are loaded first, then generated system values are
        applied.
        '''
        self._entry_metadata = EntryMetadata()
        self._apply_metadata_from_mongo(self.upload, self._entry_metadata)
        self._apply_metadata_from_process(self._entry_metadata)

        self._parser_results = EntryArchive()
        self._parser_results.metadata = self._entry_metadata

    def _apply_metadata_from_file(self, logger):
        # metadata file name defined in nomad.config nomad_metadata.yaml/json
        # which can be placed in the directory containing the mainfile or somewhere up
        # highest priority is directory with mainfile
        metadata_file = config.process.metadata_file_name
        metadata_dir = os.path.dirname(self.mainfile_file.os_path)
        upload_raw_dir = self.upload_files._raw_dir.os_path

        metadata = {}
        metadata_part = None
        # apply the nomad files of the current directory and parent directories
        while True:
            metadata_part = self.upload.metadata_file_cached(
                os.path.join(metadata_dir, metadata_file))
            for key, val in metadata_part.items():
                if key in ['entries', 'oasis_datasets']:
                    continue
                metadata.setdefault(key, val)

            if metadata_dir == upload_raw_dir:
                break

            metadata_dir = os.path.dirname(metadata_dir)

        # Top-level nomad file can also contain an entries dict with entry
        # metadata per mainfile as key. This takes precedence of the other files.
        entries = metadata_part.get('entries', {})
        metadata_part = entries.get(self.mainfile, {})
        for key, val in metadata_part.items():
            metadata[key] = val

        if len(metadata) > 0:
            logger.info('Apply user metadata from nomad.yaml/json file(s)')

        for key, val in metadata.items():
            if key == 'entries':
                continue

            definition = _editable_metadata.get(key, None)

            if definition is None:
                logger.warn('Users cannot set metadata', quantity=key)
                continue

            try:
                self._entry_metadata.m_set(definition, val)
            except Exception as e:
                logger.error(
                    'Could not apply user metadata from nomad.yaml/json file',
                    quantitiy=definition.name, exc_info=e)

    def _apply_metadata_from_process(self, entry_metadata: EntryMetadata):
        '''
        Applies metadata generated when processing or re-processing an entry to `entry_metadata`.
        '''
        entry_metadata.nomad_version = config.meta.version
        entry_metadata.nomad_commit = config.meta.commit
        entry_metadata.calc_hash = self.upload_files.calc_hash(self.mainfile)
        entry_metadata.files = self.upload_files.calc_files(self.mainfile)
        entry_metadata.last_processing_time = datetime.utcnow()
        entry_metadata.processing_errors = []

    def _apply_metadata_from_mongo(self, upload: 'Upload', entry_metadata: EntryMetadata):
        '''
        Loads entry metadata from mongo (that is: from `self` and the provided `upload` object)
        and applies the values to `entry_metadata`.
        '''
        assert upload.upload_id == self.upload_id, 'Could not apply metadata: upload_id mismatch'
        # Upload metadata
        for quantity_name in _mongo_upload_metadata:
            setattr(entry_metadata, quantity_name, getattr(upload, quantity_name))
        # Entry metadata
        for quantity_name in _mongo_entry_metadata:
            setattr(entry_metadata, quantity_name, getattr(self, quantity_name))
        # Special case: domain. May be derivable from mongo, or may have to be read from the archive
        if self.parser_name is not None:
            parser = parser_dict[self.parser_name]
            if parser.domain:
                entry_metadata.domain = parser.domain

    def _apply_metadata_to_mongo_entry(self, entry_metadata: EntryMetadata):
        '''
        Applies the metadata fields that are stored on the mongo entry level to self.
        In other words, basically the reverse operation of :func:`_apply_metadata_from_mongo`,
        but excluding upload level metadata and system fields (like mainfile, parser_name etc.).
        '''
        entry_metadata_dict = entry_metadata.m_to_dict(include_defaults=True)
        for quantity_name in _mongo_entry_metadata_except_system_fields:
            setattr(self, quantity_name, entry_metadata_dict.get(quantity_name))

    def set_mongo_entry_metadata(self, *args, **kwargs):
        '''
        Sets the entry level metadata in mongo. Expects either a positional argument
        which is an instance of :class:`EntryMetadata` or keyword arguments with data to set.
        '''
        assert not (args and kwargs), 'Cannot provide both keyword arguments and a positional argument'
        if args:
            assert len(args) == 1 and isinstance(args[0], EntryMetadata), (
                'Expected exactly one keyword argument of type `EntryMetadata`')
            self._apply_metadata_to_mongo_entry(args[0])
        else:
            for key, value in kwargs.items():
                if key in _mongo_entry_metadata_except_system_fields:
                    setattr(self, key, value)
                else:
                    assert False, f'Cannot set metadata quantity: {key}'

    def full_entry_metadata(self, upload: 'Upload') -> EntryMetadata:
        '''
        Returns a complete set of :class:`EntryMetadata` including
        both the mongo metadata and the metadata from the archive.

        Arguments:
            upload: The :class:`Upload` to which this entry belongs. Upload level metadata
                and the archive files will be read from this object.
        '''
        assert upload.upload_id == self.upload_id, 'Mismatching upload_id encountered'
        archive = upload.upload_files.read_archive(self.calc_id)
        try:
            # instead of loading the whole archive, it should be enough to load the
            # parts that are referenced by section_metadata/EntryMetadata
            # TODO somehow it should determine which root setions too load from the metainfo
            # or configuration
            calc_archive = archive[self.calc_id]
            entry_archive_dict = {section_metadata: calc_archive[section_metadata].to_dict()}
            if section_workflow in calc_archive:
                for workflow in calc_archive[section_workflow]:
                    entry_archive_dict.setdefault(section_workflow, [])
                    entry_archive_dict[section_workflow].append(workflow.to_dict())
            if section_results in calc_archive:
                entry_archive_dict[section_results] = calc_archive[section_results].to_dict()
            entry_metadata = datamodel.EntryArchive.m_from_dict(entry_archive_dict)[section_metadata]
            self._apply_metadata_from_mongo(upload, entry_metadata)
            return entry_metadata
        except KeyError:
            # Due hard processing failures, it might be possible that an entry might not
            # have an archive. Return the metadata that is available.
            if self._entry_metadata is not None:
                return self._entry_metadata
            else:
                return self.mongo_metadata(upload)

    def mongo_metadata(self, upload: 'Upload') -> EntryMetadata:
        '''
        Returns a :class:`EntryMetadata` with mongo metadata only
        (fetched from `self` and `upload`), no archive metadata.
        '''
        assert upload.upload_id == self.upload_id, 'Mismatching upload_id encountered'
        entry_metadata = EntryMetadata()
        self._apply_metadata_from_mongo(upload, entry_metadata)
        return entry_metadata

    @property
    def upload_files(self) -> StagingUploadFiles:
        if not self._upload_files:
            self._upload_files = StagingUploadFiles(self.upload_id)
        return self._upload_files

    def get_logger(self, **kwargs):
        '''
        Returns a wrapped logger that additionally saves all entries to the calculation
        processing log in the archive.
        '''
        logger = super().get_logger()
        logger = logger.bind(
            upload_id=self.upload_id, mainfile=self.mainfile, calc_id=self.calc_id,
            parser=self.parser_name, **kwargs)

        if self._calc_proc_logs is None:
            self._calc_proc_logs = []

        def save_to_calc_log(logger, method_name, event_dict):
            try:
                # sanitize the event_dict, because all kinds of values might have been added
                dump_dict = {key: str(value) for key, value in event_dict.items()}
                dump_dict.update(level=method_name.upper())
                self._calc_proc_logs.append(dump_dict)

                if method_name == 'error':
                    error = event_dict.get('event', None)
                    if error is not None:
                        self._entry_metadata.processing_errors.append(error)

            except Exception:
                # Exceptions here will cause indefinite loop
                pass

            return event_dict

        return wrap_logger(logger, processors=_log_processors + [save_to_calc_log])

    @process(is_child=True)
    def process_calc(self, reprocess_settings: Dict[str, Any] = None):
        '''
        Processes (or reprocesses) a calculation.

        Arguments:
            reprocess_settings: An optional dictionary specifying the behaviour when reprocessing.
                Settings that are not specified are defaulted. See `config.reprocess` for
                available options and the configured default values.
        '''
        logger = self.get_logger()
        if self.upload is None:
            logger.error('calculation upload does not exist')

        settings = config.reprocess.customize(reprocess_settings)  # Add default settings

        # 1. Determine if we should parse or not
        self.set_last_status_message('Determining action')
        # If this entry has been processed before, or imported from a bundle, nomad_version
        # should be set. If not, this is the initial processing.
        self._is_initial_processing = self.nomad_version is None
        self._perform_index = self._is_initial_processing or settings.get('index_invidiual_entries', True)
        if not self.upload.published or self._is_initial_processing:
            should_parse = True
        elif not settings.reprocess_existing_entries:
            should_parse = False
        else:
            if settings.rematch_published and not settings.use_original_parser:
                with utils.timer(logger, 'parser matching executed'):
                    parser = match_parser(
                        self.upload_files.raw_file_object(self.mainfile).os_path, strict=False)
            else:
                parser = parser_dict[self.parser_name]

            if parser is None:
                # Should only be possible if the upload is published and we have
                logger.warn('no parser matches during process, not updating the entry')
                self.warnings = ['no matching parser found during processing']
            else:
                should_parse = True
                parser_changed = self.parser_name != parser.name and parser_dict[self.parser_name].name != parser.name
                if parser_changed:
                    if not settings.use_original_parser:
                        logger.info(
                            'different parser matches during process, use new parser',
                            parser=parser.name)
                        self.parser_name = parser.name  # Parser renamed

        # 2. Either parse the entry, or preserve it as it is.
        if should_parse:
            # 2a. Parse (or reparse) it
            try:
                self.set_last_status_message('Initializing metadata')
                self._initialize_metadata_for_processing()

                if len(self._entry_metadata.files) >= config.auxfile_cutoff:
                    self.warning(
                        'This calc has many aux files in its directory. '
                        'Have you placed many calculations in the same directory?')

                self.parsing()
                self.normalizing()
                self.archiving()
            finally:
                # close loghandler that was not closed due to failures
                try:
                    if self._parser_results and self._parser_results.m_resource:
                        self._parser_results.metadata = None
                        self._parser_results.m_resource.unload()
                except Exception as e:
                    logger.error('could not unload processing results', exc_info=e)
        elif self.upload.published:
            # 2b. Keep published entry as it is
            self.set_last_status_message('Preserving entry data')
            try:
                upload_files = PublicUploadFiles(self.upload_id)
                with upload_files.read_archive(self.calc_id) as archive:
                    self.upload_files.write_archive(self.calc_id, archive[self.calc_id].to_dict())

            except Exception as e:
                logger.error('could not copy archive for non-reprocessed entry', exc_info=e)
                raise
        else:
            # 2b. Keep staging entry as it is
            pass

    def on_fail(self):
        # in case of failure, create a minimum set of metadata and mark
        # processing failure
        try:
            if self._entry_metadata is None:
                self._initialize_metadata_for_processing()
            self._entry_metadata.processed = False

            try:
                self._apply_metadata_to_mongo_entry(self._entry_metadata)
            except Exception as e:
                self.get_logger().error(
                    'could not apply entry metadata to entry', exc_info=e)

            try:
                self._entry_metadata.apply_archvie_metadata(self._parser_results)
            except Exception as e:
                self.get_logger().error(
                    'could not apply domain metadata to entry', exc_info=e)
        except Exception as e:
            self._parser_results = EntryArchive(
                entry_id=self._parser_results.entry_id,
                metadata=self._parser_results.metadata,
                processing_logs=self._parser_results.processing_logs)

            self.get_logger().error(
                'could not create minimal metadata after processing failure', exc_info=e)

        if self._perform_index:
            try:
                search.index(self._parser_results)
            except Exception as e:

                search.index(self._parser_results)
                self.get_logger().error(
                    'could not index archive after processing failure', exc_info=e)

        try:
            self.write_archive(self._parser_results)
        except Exception as e:
            self.get_logger().error(
                'could not write archive after processing failure', exc_info=e)

    def parent(self) -> 'Upload':
        return self.upload

    def parsing(self):
        ''' The process step that encapsulates all parsing related actions. '''
        self.set_last_status_message('Parsing mainfile')
        context = dict(step=self.parser_name)
        logger = self.get_logger(**context)
        parser = parser_dict[self.parser_name]
        self._entry_metadata.parser_name = self.parser_name

        with utils.timer(logger, 'parser executed', input_size=self.mainfile_file.size):
            if not config.process.reuse_parser:
                if isinstance(parser, parsing.FairdiParser):
                    try:
                        parser = parser.__class__()
                    except Exception as e:
                        raise ProcessFailure(
                            'could not re-create parser instance',
                            exc_info=e, error=str(e), **context)
            try:
                parser.parse(
                    self.upload_files.raw_file_object(self.mainfile).os_path,
                    self._parser_results, logger=logger)

            except Exception as e:
                raise ProcessFailure('parser failed with exception', exc_info=e, error=str(e), **context)
            except SystemExit:
                raise ProcessFailure('parser raised system exit', error='system exit', **context)

    def process_phonon(self):
        """Function that is run for phonon calculation before cleanup.
        This task is run by the celery process that is calling the join for the
        upload.

        This function re-opens the Archive for this calculation to add method
        information from another referenced archive. Updates the method
        information as well as the DFT domain metadata.
        """
        try:
            logger = self.get_logger()

            # Open the archive of the phonon calculation.
            upload_files = StagingUploadFiles(self.upload_id)
            with upload_files.read_archive(self.calc_id) as archive:
                arch = archive[self.calc_id]
                phonon_archive = EntryArchive.m_from_dict(arch.to_dict())
            self._entry_metadata = phonon_archive.metadata
            self._calc_proc_logs = phonon_archive.processing_logs

            # Re-create the parse results
            self._parser_results = phonon_archive

            # Read in the first referenced calculation. The reference is given as
            # an absolute path which needs to be converted into a path that is
            # relative to upload root.
            scc = self._parser_results.run[0].calculation[0]
            calculation_refs = scc.calculations_path
            if calculation_refs is None:
                logger.error("No calculation_to_calculation references found")
                return

            relative_ref = scc.calculations_path[0]
            ref_id = generate_entry_id(self.upload_id, relative_ref)

            with upload_files.read_archive(ref_id) as archive:
                arch = archive[ref_id]
                ref_archive = EntryArchive.m_from_dict(arch.to_dict())

            # Get method information directly from the referenced calculation.
            ref_method = ref_archive.results.method
            if not ref_method:
                logger.error("No method information available in referenced calculation.")
                return

            # Overwrite old entry with new data. The metadata is updated with
            # new timestamp and method details taken from the referenced
            # archive. The program name and version are kept.
            ref_method.simulation.program_name = self._parser_results.results.method.simulation.program_name
            ref_method.simulation.program_version = self._parser_results.results.method.simulation.program_version
            self._parser_results.results.method = ref_method
            self._entry_metadata.last_processing_time = datetime.utcnow()
        except Exception as e:
            logger.error("Could not retrieve method information for phonon calculation.", exc_info=e)
            if self._entry_metadata is None:
                self._initialize_metadata_for_processing()
            self._entry_metadata.processed = False
        finally:
            # persist the calc metadata
            with utils.timer(logger, 'calc metadata saved'):
                self._apply_metadata_to_mongo_entry(self._entry_metadata)

            # index in search
            with utils.timer(logger, 'calc metadata indexed'):
                assert self._parser_results.metadata == self._entry_metadata
                search.index(self._parser_results)

            # persist the archive
            with utils.timer(
                    logger, 'calc archived',
                    input_size=self.mainfile_file.size) as log_data:

                archive_size = self.write_archive(self._parser_results)
                log_data.update(archive_size=archive_size)

    def normalizing(self):
        ''' The process step that encapsulates all normalizing related actions. '''
        self.set_last_status_message('Normalizing')
        # allow normalizer to access and add data to the entry metadata
        if self._parser_results.metadata is None:
            self._parser_results.m_add_sub_section(
                datamodel.EntryArchive.metadata, self._entry_metadata)

        for normalizer in normalizers:
            if normalizer.domain is not None and normalizer.domain != parser_dict[self.parser_name].domain:
                continue

            normalizer_name = normalizer.__name__
            context = dict(normalizer=normalizer_name, step=normalizer_name)
            logger = self.get_logger(**context)

            with utils.timer(logger, 'normalizer executed', input_size=self.mainfile_file.size):
                try:
                    normalizer(self._parser_results).normalize(logger=logger)
                    logger.info('normalizer completed successfull', **context)
                except Exception as e:
                    raise ProcessFailure('normalizer failed with exception', exc_info=e, error=str(e), **context)

    def archiving(self):
        ''' The process step that encapsulates all archival related actions. '''
        self.set_last_status_message('Archiving')
        logger = self.get_logger()

        self._entry_metadata.apply_archvie_metadata(self._parser_results)
        self._entry_metadata.processed = True

        if self.upload.publish_directly:
            self._entry_metadata.published |= True

        if self._is_initial_processing:
            try:
                self._apply_metadata_from_file(logger)
            except Exception as e:
                logger.error('could not process user metadata in nomad.yaml/json file', exc_info=e)

        # persist the calc metadata
        with utils.timer(logger, 'calc metadata saved'):
            self._apply_metadata_to_mongo_entry(self._entry_metadata)

        # index in search
        if self._perform_index:
            with utils.timer(logger, 'calc metadata indexed'):
                assert self._parser_results.metadata == self._entry_metadata
                search.index(self._parser_results)

        # persist the archive
        with utils.timer(
                logger, 'calc archived',
                input_size=self.mainfile_file.size) as log_data:

            archive_size = self.write_archive(self._parser_results)
            log_data.update(archive_size=archive_size)

    def write_archive(self, archive: EntryArchive):
        # save the archive mongo entry
        try:
            if self._entry_metadata.processed:
                write_partial_archive_to_mongo(archive)
        except Exception as e:
            self.get_logger().error('could not write mongodb archive entry', exc_info=e)

        # add the processing logs to the archive
        def filter_processing_logs(logs):
            if len(logs) > 100:
                return [
                    log for log in logs
                    if log.get('level') != 'DEBUG']
            return logs

        if self._calc_proc_logs is None:
            self._calc_proc_logs = []

        if archive is not None:
            archive = archive.m_copy()
        else:
            archive = datamodel.EntryArchive()

        if archive.metadata is None:
            archive.m_add_sub_section(datamodel.EntryArchive.metadata, self._entry_metadata)

        archive.processing_logs = filter_processing_logs(self._calc_proc_logs)

        # save the archive msg-pack
        try:
            return self.upload_files.write_archive(self.calc_id, archive.m_to_dict())
        except Exception as e:
            # most likely failed due to domain data, try to write metadata and processing logs
            archive = datamodel.EntryArchive()
            archive.m_add_sub_section(datamodel.EntryArchive.metadata, self._entry_metadata)
            archive.processing_logs = filter_processing_logs(self._calc_proc_logs)
            self.upload_files.write_archive(self.calc_id, archive.m_to_dict())
            raise

    def __str__(self):
        return 'calc %s calc_id=%s upload_id%s' % (super().__str__(), self.calc_id, self.upload_id)


class Upload(Proc):
    '''
    Represents uploads in the databases. Provides persistence access to the files storage,
    and processing state.

    Attributes:
        upload_id: The upload id generated by the database or the uploaded NOMAD deployment.
        upload_name: Optional user provided upload name.
        upload_create_time: Datetime of creation of the upload.
        external_db: the repository or external database where the original data resides
        main_author: The id of the main author of this upload (normally its creator).
        coauthors: A list of upload coauthors.
        reviewers: A user provided list of reviewers. Reviewers can see the whole upload,
            also if it is unpublished or embargoed.
        publish_time: Datetime when the upload was initially published on this NOMAD deployment.
        last_update: Datetime of the last modifying process run (publish, processing, upload).

        publish_directly: Boolean indicating that this upload should be published after initial processing.
        from_oasis: Boolean indicating that this upload is coming from another NOMAD deployment.
        oasis_id: The deployment id of the NOMAD that uploaded the upload.
        published_to: A list of deployment ids where this upload has been successfully uploaded to.
    '''
    id_field = 'upload_id'

    upload_id = StringField(primary_key=True)
    upload_name = StringField(default=None)
    upload_create_time = DateTimeField(required=True)
    external_db = StringField()
    main_author = StringField(required=True)
    coauthors = ListField(StringField())
    reviewers = ListField(StringField())
    last_update = DateTimeField()
    publish_time = DateTimeField()
    embargo_length = IntField(default=0, required=True)
    license = StringField(default='CC BY 4.0', required=True)

    from_oasis = BooleanField(default=False)
    oasis_deployment_id = StringField(default=None)
    published_to = ListField(StringField())

    publish_directly = BooleanField(default=False)

    meta: Any = {
        'strict': False,
        'indexes': [
            'main_author', 'process_status', 'upload_create_time', 'publish_time'
        ]
    }

    @property
    def viewers(self):
        # It is possible to set a user as both coauthor and reviewer, need to ensure no duplicates
        rv = [self.main_author] + self.coauthors
        for user_id in self.reviewers:
            if user_id not in rv:
                rv.append(user_id)
        return rv

    @property
    def writers(self):
        return [self.main_author] + self.coauthors

    def __init__(self, **kwargs):
        kwargs.setdefault('upload_create_time', datetime.utcnow())
        super().__init__(**kwargs)
        self._upload_files: UploadFiles = None

    @lru_cache()
    def metadata_file_cached(self, path):
        for ext in config.process.metadata_file_extensions:
            full_path = '%s.%s' % (path, ext)
            if os.path.isfile(full_path):
                try:
                    with open(full_path) as f:
                        if full_path.endswith('.json'):
                            return json.load(f)
                        elif full_path.endswith('.yaml') or full_path.endswith('.yml'):
                            return yaml.load(f, Loader=getattr(yaml, 'FullLoader'))
                        else:
                            return {}
                except Exception as e:
                    self.get_logger().warn('could not parse nomad.yaml/json', path=path, exc_info=e)
                    # ignore the file contents if the file is not parsable
                    pass
        return {}

    @classmethod
    def get(cls, id: str) -> 'Upload':
        return cls.get_by_id(id, 'upload_id')

    @classmethod
    def user_uploads(cls, user: datamodel.User, **kwargs) -> Sequence['Upload']:
        ''' Returns all uploads for the given user. Kwargs are passed to mongo query. '''
        return cls.objects(main_author=str(user.user_id), **kwargs)

    @property
    def main_author_user(self) -> datamodel.User:
        return datamodel.User.get(self.main_author)

    @property
    def published(self) -> bool:
        return self.publish_time is not None

    @property
    def with_embargo(self) -> bool:
        return self.embargo_length > 0

    def get_logger(self, **kwargs):
        logger = super().get_logger()
        main_author_user = self.main_author_user
        main_author_name = '%s %s' % (main_author_user.first_name, main_author_user.last_name)
        # We are not using 'main_author' because logstash (?) will filter these entries ?!
        logger = logger.bind(
            upload_id=self.upload_id, upload_name=self.upload_name, main_author_name=main_author_name,
            main_author=self.main_author, **kwargs)
        return logger

    @classmethod
    def create(cls, main_author: datamodel.User = None, **kwargs) -> 'Upload':
        '''
        Creates a new upload for the given main_author, a user given upload_name is optional.
        It will populate the record with a signed url and pending :class:`UploadProc`.
        The upload will be already saved to the database.

        Arguments:
            main_author: The main author of the upload.
        '''
        # use kwargs to keep compatibility with super method
        assert main_author is not None, 'No `main_author` provided.'
        if 'upload_id' not in kwargs:
            kwargs.update(upload_id=utils.create_uuid())
        kwargs.update(main_author=main_author.user_id)
        self = super().create(**kwargs)

        return self

    @classmethod
    def create_skeleton_from_bundle(cls, bundle: UploadBundle) -> 'Upload':
        '''
        Creates a minimalistic "skeleton" from the provided upload bundle (basically just
        with the right upload_id and user), on which we can initiate the :func:`import_bundle`
        process to import the bundle data.
        '''
        bundle_info = bundle.bundle_info
        keys_exist(bundle_info, ('upload_id', 'upload.main_author'), 'Missing key in bundle_info.json: {key}')
        upload_id = bundle_info['upload_id']
        main_author = bundle_info['upload']['main_author']
        try:
            Upload.get(upload_id)
            assert False, f'Upload with id {upload_id} already exists'
        except KeyError:
            pass
        main_author_user = datamodel.User.get(user_id=main_author)
        assert main_author_user is not None, f'Invalid main_author: {main_author}'
        return Upload.create(
            upload_id=upload_id,
            main_author=main_author_user)

    def delete(self):
        ''' Deletes this upload process state entry and its calcs. '''
        Calc.objects(upload_id=self.upload_id).delete()
        super().delete()

    def delete_upload_local(self):
        '''
        Deletes the upload, including its processing state and
        staging files. Local version without celery processing.
        '''
        logger = self.get_logger(upload_size=self.upload_files.size)

        with utils.lnr(logger, 'upload delete failed'):
            with utils.timer(logger, 'upload deleted from index'):
                search.delete_upload(self.upload_id, refresh=True)

            with utils.timer(logger, 'upload partial archives deleted'):
                calc_ids = [calc.calc_id for calc in Calc.objects(upload_id=self.upload_id)]
                delete_partial_archives_from_mongo(calc_ids)

            with utils.timer(logger, 'upload files deleted'):
                self.upload_files.delete()

            self.delete()

    @process(is_blocking=True)
    def delete_upload(self):
        '''
        Deletes the upload, including its processing state and
        staging files. This starts the celery process of deleting the upload.
        '''
        self.delete_upload_local()

        return ProcessStatus.DELETED  # Signal deletion to the process framework

    @process(is_blocking=True)
    def publish_upload(self, embargo_length: int = None):
        '''
        Moves the upload out of staging to the public area. It will
        pack the staging upload files in to public upload files.
        '''
        assert self.processed_calcs > 0

        logger = self.get_logger(upload_size=self.upload_files.size)
        logger.info('started to publish')

        if embargo_length is not None:
            assert 0 <= embargo_length <= 36, 'Invalid embargo length, must be between 0 and 36 months'
            self.embargo_length = embargo_length

        with utils.lnr(logger, 'publish failed'):
            with self.entries_metadata() as entries:
                if isinstance(self.upload_files, StagingUploadFiles):
                    with utils.timer(logger, 'staged upload files packed'):
                        self.staging_upload_files.pack(entries, with_embargo=self.with_embargo)

                with utils.timer(logger, 'index updated'):
                    search.publish(entries)

                if isinstance(self.upload_files, StagingUploadFiles):
                    with utils.timer(logger, 'upload staging files deleted'):
                        self.upload_files.delete()
                        self.publish_time = datetime.utcnow()
                        self.last_update = datetime.utcnow()
                        self.save()
                else:
                    self.last_update = datetime.utcnow()
                    self.save()

    @process(is_blocking=True)
    def publish_externally(self, embargo_length: int = None):
        '''
        Uploads the already published upload to a different NOMAD deployment. This is used
        to push uploads from an OASIS to the central NOMAD. Makes use of the upload bundle
        functionality.
        '''
        assert self.published, \
            'Only published uploads can be published to the central NOMAD.'
        assert config.oasis.central_nomad_deployment_id not in self.published_to, \
            'Upload is already published to the central NOMAD.'

        tmp_dir = create_tmp_dir('export_' + self.upload_id)
        bundle_path = os.path.join(tmp_dir, self.upload_id + '.zip')
        try:
            self.set_last_status_message('Creating bundle.')

            self.export_bundle(
                export_as_stream=False, export_path=bundle_path,
                zipped=True, move_files=False, overwrite=False,
                include_raw_files=True, include_archive_files=True, include_datasets=True)

            # upload to central NOMAD
            self.set_last_status_message('Uploading bundle to central NOMAD.')
            upload_auth = client.Auth(
                user=config.keycloak.username,
                password=config.keycloak.password)
            upload_parameters: Dict[str, Any] = {}
            if embargo_length is not None:
                upload_parameters.update(embargo_length=embargo_length)
            upload_url = f'{config.oasis.central_nomad_api_url}/v1/uploads/bundle'

            with open(bundle_path, 'rb') as f:
                response = requests.post(
                    upload_url, params=upload_parameters, data=f, auth=upload_auth)

            if response.status_code != 200:
                self.get_logger().error(
                    'Could not upload to central NOMAD',
                    status_code=response.status_code, body=response.text)
                raise ProcessFailure('Error message from central NOMAD: {response.text}')

            self.published_to.append(config.oasis.central_nomad_deployment_id)
        finally:
            PathObject(tmp_dir).delete()

    @process()
    def process_upload(
            self, file_operation: Dict[str, Any] = None, reprocess_settings: Dict[str, Any] = None):
        '''
        A @process that executes a file operation (if provided), and matches, parses and normalizes
        the upload. Can be used for initial parsing or to re-parse, and can also be used
        after an upload has been published (published uploads are extracted back to the
        staging area first, and re-packed to the public area when done). Reprocessing may
        also cause existing entries to disappear (if main files have been removed from an
        upload in the staging area, or no longer match because of modified parsers, etc).

        Arguments:
            file_operation: A dictionary specifying a file operation to perform before
                the actual processing. The dictionary should contain a key `op` which defines
                the operation, either "ADD" or "DELETE". The "ADD" operation further expects
                keys named `path` (the path to the source file), `target_dir` (the destination
                path relative to the raw folder), and `temporary` (if the source file and parent
                folder should be deleted when done). The "DELETE" operation expects a key named
                `path` (specifying the path relative to the raw folder which is to be deleted).
            reprocess_settings: An optional dictionary specifying the behaviour when reprocessing.
                Settings that are not specified are defaulted. See `config.reprocess` for
                available options and the configured default values.
        '''
        return self._process_upload_local(file_operation, reprocess_settings)

    def _process_upload_local(self, file_operation: Dict[str, Any] = None, reprocess_settings: Dict[str, Any] = None):
        '''
        The function doing the actual processing, but locally, not as a @process.
        See :func:`process_upload`
        '''
        logger = self.get_logger()
        logger.info('starting to (re)process')

        self.update_files(file_operation)
        self.parse_all(reprocess_settings)
        self.set_last_status_message('Waiting for entry results')
        return ProcessStatus.WAITING_FOR_RESULT

    @property
    def upload_files(self) -> UploadFiles:
        upload_files_class = StagingUploadFiles if not self.published else PublicUploadFiles

        if not self._upload_files or not isinstance(self._upload_files, upload_files_class):
            self._upload_files = upload_files_class(self.upload_id)

        return self._upload_files

    @property
    def staging_upload_files(self) -> StagingUploadFiles:
        return self.upload_files.to_staging_upload_files()

    def update_files(self, file_operation: Dict[str, Any]):
        '''
        The process step performed before the actual parsing/normalizing: executes the pending
        file operations.
        '''
        logger = self.get_logger()

        if self.published and PublicUploadFiles.exists_for(self.upload_id):
            # Clean up staging files, if they exist, and unpack the public files to the
            # staging area.
            self.set_last_status_message('Refreshing staging files')
            self._cleanup_staging_files()
            with utils.timer(logger, 'upload extracted'):
                self.upload_files.to_staging_upload_files(create=True)
        elif not StagingUploadFiles.exists_for(self.upload_id):
            # Create staging files
            self.set_last_status_message('Creating staging files')
            StagingUploadFiles(self.upload_id, create=True)

        staging_upload_files = self.staging_upload_files
        # Execute the requested file_operation, if any
        if file_operation:
            op = file_operation['op']
            if op == 'ADD':
                self.set_last_status_message('Adding files')
                with utils.timer(logger, 'Adding file(s) to upload', upload_size=staging_upload_files.size):
                    staging_upload_files.add_rawfiles(
                        file_operation['path'],
                        file_operation['target_dir'],
                        cleanup_source_file_and_dir=file_operation['temporary'])
            elif op == 'DELETE':
                self.set_last_status_message('Deleting files')
                with utils.timer(logger, 'Deleting files or folders from upload'):
                    staging_upload_files.delete_rawfiles(file_operation['path'])
            else:
                raise ValueError(f'Unknown operation {op}')

    def _preprocess_files(self, path):
        '''
        Some files need preprocessing. Currently we need to add a stripped POTCAR version
        and always restrict/embargo the original.
        '''
        if os.path.basename(path).startswith('POTCAR'):
            # create checksum
            hash = hashlib.sha224()
            with open(self.staging_upload_files.raw_file_object(path).os_path, 'rb') as orig_f:
                for line in orig_f.readlines():
                    hash.update(line)

            checksum = hash.hexdigest()

            # created stripped POTCAR
            stripped_path = path + '.stripped'
            with open(self.staging_upload_files.raw_file_object(stripped_path).os_path, 'wt') as stripped_f:
                stripped_f.write('Stripped POTCAR file. Checksum of original file (sha224): %s\n' % checksum)
            os.system(
                '''
                    awk < '%s' >> '%s' '
                    BEGIN { dump=1 }
                    /End of Dataset/ { dump=1 }
                    dump==1 { print }
                    /END of PSCTR/ { dump=0 }'
                ''' % (
                    self.staging_upload_files.raw_file_object(path).os_path,
                    self.staging_upload_files.raw_file_object(stripped_path).os_path))

    def match_mainfiles(self) -> Iterator[Tuple[str, Parser]]:
        '''
        Generator function that matches all files in the upload to all parsers to
        determine the upload's mainfiles.

        Returns:
            Tuples of (mainfile raw path, parser)
        '''
        staging_upload_files = self.staging_upload_files

        metadata = self.metadata_file_cached(
            os.path.join(self.upload_files.os_path, 'raw', config.process.metadata_file_name))
        skip_matching = metadata.get('skip_matching', False)
        entries_metadata = metadata.get('entries', {})

        for path_info in staging_upload_files.raw_directory_list(recursive=True, files_only=True):
            self._preprocess_files(path_info.path)

            if skip_matching and path_info.path not in entries_metadata:
                continue

            try:
                parser = match_parser(staging_upload_files.raw_file_object(path_info.path).os_path)
                if parser is not None:
                    yield path_info.path, parser
            except Exception as e:
                self.get_logger().error(
                    'exception while matching pot. mainfile',
                    mainfile=path_info.path, exc_info=e)

    def parse_all(self, reprocess_settings: Dict[str, Any] = None):
        '''
        The process step used to identify mainfile/parser combinations among the upload's files,
        creates respective :class:`Calc` instances, and triggers their processing.

        Arguments:
            reprocess_settings: An optional dictionary specifying the behaviour when reprocessing.
                Settings that are not specified are defaulted. See `config.reprocess` for
                available options and the configured default values.
        '''
        self.set_last_status_message('Parsing all files')
        logger = self.get_logger()

        try:
            settings = config.reprocess.customize(reprocess_settings)  # Add default settings

            if not self.published or settings.rematch_published:
                with utils.timer(logger, 'matching completed'):
                    old_entries = set([entry.calc_id for entry in Calc.objects(upload_id=self.upload_id)])
                    for filename, parser in self.match_mainfiles():
                        calc_id = generate_entry_id(self.upload_id, filename)

                        try:
                            entry = Calc.get(calc_id)
                            # Matching entry already exists.
                            # Ensure that we update the parser if in staging
                            if not self.published and parser.name != entry.parser_name:
                                entry.parser_name = parser.name
                                entry.save()

                            old_entries.remove(calc_id)
                        except KeyError:
                            # No existing entry found
                            if not self.published or settings.add_matched_entries_to_published:
                                entry = Calc.create(
                                    calc_id=calc_id,
                                    mainfile=filename,
                                    parser_name=parser.name,
                                    worker_hostname=self.worker_hostname,
                                    upload_id=self.upload_id)
                                entry.save()

                    # Delete old entries
                    if len(old_entries) > 0:
                        entries_to_delete: List[str] = list(old_entries)
                        logger.warn('Some entries did not match', count=len(entries_to_delete))
                        if not self.published or settings.delete_unmatched_published_entries:
                            delete_partial_archives_from_mongo(entries_to_delete)
                            for calc_id in entries_to_delete:
                                search.delete_entry(entry_id=calc_id, update_materials=True)
                                entry = Calc.get(calc_id)
                            entry.delete()

            # reset all calcs
            # (No Calc processes *should* be running, unless something has gone wrong, and if
            # there are such processes, we can quite safely just reset them to minimize problems)
            with utils.timer(logger, 'calcs processing resetted'):
                Calc._get_collection().update_many(
                    dict(upload_id=self.upload_id),
                    {'$set': Calc.reset_pymongo_update(worker_hostname=self.worker_hostname)})

            # process call calcs
            with utils.timer(logger, 'calcs processing called'):
                for entry in Calc.objects(upload_id=self.upload_id):
                    entry.process_calc(reprocess_settings=settings)

        except Exception as e:
            # try to remove the staging copy in failure case
            logger.error('failed to trigger processing of all entries', exc_info=e)
            if self.published:
                self._cleanup_staging_files()
            raise

    def child_cls(self):
        return Calc

    def join(self):
        '''
        Called when all child processes (if any) on Calc are done. Performs phonon calculations
        and cleanup.
        '''
        # Before cleaning up, run an additional normalizer on phonon
        # calculations. TODO: This should be replaced by a more
        # extensive mechanism that supports more complex dependencies
        # between calculations.
        phonon_calculations = Calc.objects(upload_id=self.upload_id, parser_name="parsers/phonopy")
        for calc in phonon_calculations:
            calc.process_phonon()

        self.cleanup()

    def cleanup(self):
        '''
        The process step that "cleans" the processing, i.e. removed obsolete files and performs
        pending archival operations. Depends on the type of processing.
        '''
        self.set_last_status_message('Cleanup')
        logger = self.get_logger()

        if self.published:
            # We have reprocessed an already published upload
            logger.info('started to repack re-processed upload')

            with utils.timer(logger, 'staged upload files re-packed'):
                self.staging_upload_files.pack(
                    self.entries_mongo_metadata(),
                    with_embargo=self.with_embargo,
                    create=False, include_raw=False)

            self._cleanup_staging_files()
            self.last_update = datetime.utcnow()
            self.save()

        if self.publish_directly and not self.published and self.processed_calcs > 0:
            logger = self.get_logger(upload_size=self.upload_files.size)
            logger.info('started to publish upload directly')

            with utils.lnr(logger, 'publish failed'):
                with self.entries_metadata() as calcs:
                    with utils.timer(logger, 'upload staging files packed'):
                        self.staging_upload_files.pack(calcs, with_embargo=self.with_embargo)

                with utils.timer(logger, 'upload staging files deleted'):
                    self.staging_upload_files.delete()

                self.publish_time = datetime.utcnow()
                self.last_update = datetime.utcnow()
                self.save()

        with self.entries_metadata() as entries:
            with utils.timer(logger, 'upload entries and materials indexed'):
                archives = [entry.m_parent for entry in entries]
                search.index(
                    archives, update_materials=config.process.index_materials,
                    refresh=True)

        # send email about process finish
        if not self.publish_directly:
            user = self.main_author_user
            name = '%s %s' % (user.first_name, user.last_name)
            message = '\n'.join([
                'Dear %s,' % name,
                '',
                'your data %suploaded at %s has completed processing.' % (
                    '"%s" ' % (self.upload_name or ''), self.upload_create_time.isoformat()),
                'You can review your data on your upload page: %s' % config.gui_url(page='uploads'),
                '',
                'If you encounter any issues with your upload, please let us know and reply to this email.',
                '',
                'The nomad team'
            ])
            try:
                infrastructure.send_mail(
                    name=name, email=user.email, message=message, subject='Processing completed')
            except Exception as e:
                # probably due to email configuration problems
                # don't fail or present this error to clients
                self.logger.error('could not send after processing email', exc_info=e)

    def _cleanup_staging_files(self):
        if self.published and PublicUploadFiles.exists_for(self.upload_id):
            if StagingUploadFiles.exists_for(self.upload_id):
                staging_upload_files = StagingUploadFiles(self.upload_id)
                with utils.timer(self.get_logger(), 'upload staging files deleted'):
                    staging_upload_files.delete()

    def get_calc(self, calc_id) -> Calc:
        ''' Returns the upload calc with the given id or ``None``. '''
        return Calc.objects(upload_id=self.upload_id, calc_id=calc_id).first()

    @property
    def processed_calcs(self) -> int:
        '''
        The number of successfully or not successfully processed calculations. I.e.
        calculations that have finished processing.
        '''
        return Calc.objects(
            upload_id=self.upload_id, process_status__in=[
                ProcessStatus.SUCCESS, ProcessStatus.FAILURE]).count()

    @property
    def total_calcs(self) -> int:
        ''' The number of all calculations. '''
        return Calc.objects(upload_id=self.upload_id).count()

    @property
    def failed_calcs(self) -> int:
        ''' The number of calculations with failed processing. '''
        return Calc.objects(upload_id=self.upload_id, process_status=ProcessStatus.FAILURE).count()

    @property
    def processing_calcs(self) -> int:
        ''' The number of calculations currently processing. '''
        return Calc.objects(
            upload_id=self.upload_id, process_status__in=ProcessStatus.STATUSES_PROCESSING).count()

    def all_calcs(self, start, end, order_by=None) -> Sequence[Calc]:
        '''
        Returns all calculations, paginated and ordered.

        Arguments:
            start: the start index of the requested page
            end: the end index of the requested page
            order_by: the property to order by
        '''
        query = Calc.objects(upload_id=self.upload_id)[start:end]
        if not order_by:
            return query
        if type(order_by) == str:
            return query.order_by(order_by)
        assert type(order_by) == tuple, 'order_by must be a string or a tuple if set'
        return query.order_by(*order_by)

    @property
    def outdated_calcs(self) -> Sequence[Calc]:
        ''' All successfully processed and outdated calculations. '''
        return Calc.objects(
            upload_id=self.upload_id, process_status=ProcessStatus.SUCCESS,
            nomad_version__ne=config.meta.version)

    @property
    def calcs(self) -> Sequence[Calc]:
        ''' All successfully processed calculations. '''
        return Calc.objects(upload_id=self.upload_id, process_status=ProcessStatus.SUCCESS)

    @contextmanager
    def entries_metadata(self) -> Iterator[List[EntryMetadata]]:
        '''
        This is the :py:mod:`nomad.datamodel` transformation method to transform
        processing upload's entries into list of :class:`EntryMetadata` objects.
        '''
        try:
            # read all calc objects first to avoid missing curser errors
            yield [
                calc.full_entry_metadata(self)
                for calc in list(Calc.objects(upload_id=self.upload_id))]

        finally:
            self.upload_files.close()  # Because full_entry_metadata reads the archive files.

    def entries_mongo_metadata(self) -> List[EntryMetadata]:
        '''
        Returns a list of :class:`EntryMetadata` containing the mongo metadata
        only, for all entries of this upload.
        '''
        return [calc.mongo_metadata(self) for calc in Calc.objects(upload_id=self.upload_id)]

    @process()
    def set_upload_metadata(self, metadata: Dict[str, Any]):
        '''
        TODO: DEPRECATED - REMOVE ASAP
        A @process which sets upload level metadata (metadata that is editable and set
        on the upload level, rather than the entry level. Some of these fields are mirrored
        from the upload to the entry metadata, however).

        Arguments:
            metadata: a dictionary with metadata to set. See the class
                :class:`datamodel.UploadMetadata` for possible values.
                Keys with None-values are left unchanged.
        '''
        self.set_upload_metadata_local(metadata)

    def set_upload_metadata_local(self, metadata: Dict[str, Any]):
        '''
        The method that actually sets the upload metadata, but locally, not as a @process.
        See :func:`set_upload_metadata`.
        '''
        logger = self.get_logger()
        upload_metadata = UploadMetadata.m_from_dict(metadata)

        need_to_reindex = False
        need_to_repack = False
        if upload_metadata.upload_name is not None:
            self.upload_name = upload_metadata.upload_name
            need_to_reindex = True
        if upload_metadata.embargo_length is not None:
            assert 0 <= upload_metadata.embargo_length <= 36, 'Invalid `embargo_length`, must be between 0 and 36 months'
            if self.published and self.with_embargo != (upload_metadata.embargo_length > 0):
                need_to_repack = True
                need_to_reindex = True
            self.embargo_length = upload_metadata.embargo_length
        if upload_metadata.main_author is not None:
            self.main_author = upload_metadata.main_author.user_id
            need_to_reindex = True
        if upload_metadata.upload_create_time is not None:
            self.upload_create_time = upload_metadata.upload_create_time
            need_to_reindex = True

        self.save()

        if need_to_repack:
            PublicUploadFiles(self.upload_id).re_pack(with_embargo=self.with_embargo)

        if need_to_reindex and self.total_calcs > 0:
            # Update entries and elastic search
            with self.entries_metadata() as entries_metadata:
                with utils.timer(logger, 'index updated'):
                    search.update_metadata(
                        entries_metadata, update_materials=config.process.index_materials,
                        refresh=True)

    @process()
    def edit_upload_metadata(self, edit_request_json: Dict[str, Any], user_id: str):
        '''
        A @process that executes a metadata edit request, restricted to a specific upload,
        on behalf of the provided user. The `edit_request_json` should be a json dict of the
        format specified by the pydantic model :class:`MetadataEditRequest` (we need to use
        primitive data types, i.e. the json format, to be able to pass the request to a
        rabbitmq task).
        '''
        logger = self.get_logger()
        user = datamodel.User.get(user_id=user_id)
        assert not edit_request_json.get('verify_only'), 'Request has verify_only'

        # Validate the request (the @process could have been invoked directly, without previous validation)
        handler = MetadataEditRequestHandler(
            logger, user, edit_request_json=edit_request_json, upload_id=self.upload_id)
        handler.validate_request()  # Should raise errors if something looks wrong

        # Upload level metadata
        old_with_embargo = self.with_embargo
        upload_updates = handler.get_upload_metadata_to_set(self)
        if upload_updates:
            for quantity_name, mongo_value in upload_updates.items():
                setattr(self, quantity_name, mongo_value)
            self.save()

        if self.published and old_with_embargo != self.with_embargo:
            # Need to repack
            PublicUploadFiles(self.upload_id).re_pack(with_embargo=self.with_embargo)

        # Entry level metadata
        last_edit_time = datetime.utcnow()
        entry_mongo_writes = []
        updated_metadata: List[datamodel.EntryMetadata] = []
        for entry in handler.find_request_entries(self):
            entry_updates = handler.get_entry_metadata_to_set(self, entry)
            entry_updates['last_edit_time'] = last_edit_time
            # Add mongo entry update operation to bulk write list
            entry_mongo_writes.append(UpdateOne({'_id': entry.calc_id}, {'$set': entry_updates}))
            # Create updates for ES
            entry_metadata = entry.mongo_metadata(self)
            if upload_updates:
                entry_metadata.m_update_from_dict(upload_updates)
            entry_metadata.m_update_from_dict(entry_updates)
            updated_metadata.append(entry_metadata)

        # Update mongo
        if entry_mongo_writes:
            with utils.timer(logger, 'Mongo bulk write completed', nupdates=len(entry_mongo_writes)):
                mongo_result = Calc._get_collection().bulk_write(entry_mongo_writes)
            mongo_errors = mongo_result.bulk_api_result.get('writeErrors')
            assert not mongo_errors, (
                f'Failed to update mongo! {len(mongo_errors)} failures, first is {mongo_errors[0]}')
        # Update ES
        if updated_metadata:
            with utils.timer(logger, 'ES updated', nupdates=len(updated_metadata)):
                failed_es = es_update_metadata(updated_metadata, update_materials=True, refresh=True)
                assert not failed_es, f'Failed to update ES, there were {failed_es} fails'

    def entry_ids(self) -> List[str]:
        return [calc.calc_id for calc in Calc.objects(upload_id=self.upload_id)]

    def export_bundle(
            self, export_as_stream: bool, export_path: str,
            zipped: bool, move_files: bool, overwrite: bool,
            include_raw_files: bool, include_archive_files: bool, include_datasets: bool) -> Iterable[bytes]:
        '''
        Method for exporting an upload as an *upload bundle*. Upload bundles are file bundles
        used to export and import uploads between different NOMAD installations.

        Arguments:
            export_as_stream: If the bundle should be exported as a stream, rather than saved
                to a file or folder. If set to True, the `export_path` should be set to None.
                Further, `zipped` must be set to True. The stream is returned by the function.
            export_path: Defines the output path, when not exporting as a stream. Set to
                None if exporting as a stream.
            zipped: if the bundle should be zipped. Set to False to export the bundle to disk
                as an uncompressed folder. If exporting as a stream, zipped must be set to True.
            move_files: When internally moving data between different NOMAD installations,
                it may be possible to move the source files, rather than copy them. In that
                case, set this flag to True. Use with care. Requires that `zipped` and
                `export_as_stream` are set to False.
            overwrite:
                If the target file/folder should be overwritten by this operation. Not
                applicable if `export_as_stream` is True.
            include_raw_files: If the "raw" files should be included.
            include_archive_files: If the archive files (produced by parsing the raw files)
                should be included.
            include_datasets: If datasets referring to entries from this upload should be
                included.
        '''
        # Safety checks
        if export_as_stream:
            assert export_path is None, 'Cannot have `export_path` set when exporting as a stream.'
            assert zipped, 'Must have `zipped` set to True when exporting as stream.'
        else:
            assert export_path is not None, 'Must specify `export_path`.'
            assert overwrite or not os.path.exists(export_path), '`export_path` alredy exists.'
        if move_files:
            # Special case, for quickly migrating uploads between two local NOMAD installations
            assert include_raw_files and include_archive_files, (
                'Must export entire upload when using `move_files`.')
            assert not zipped and not export_as_stream, (
                'Cannot use `move_files` together withh `zipped` or `export_as_stream`.')
        assert not self.process_running or self.current_process == 'publish_externally', (
            'Upload is being processed.')

        # Create bundle_info json data
        bundle_info: Dict[str, Any] = dict(
            upload_id=self.upload_id,
            source=config.meta,  # Information about the source system, i.e. this NOMAD installation
            export_options=dict(
                include_raw_files=include_raw_files,
                include_archive_files=include_archive_files,
                include_datasets=include_datasets),
            upload=self.to_mongo().to_dict(),
            entries=[entry.to_mongo().to_dict() for entry in self.calcs])
        # Handle datasets
        dataset_ids: Set[str] = set()
        for entry_dict in bundle_info['entries']:
            entry_datasets = entry_dict.get('datasets')
            if entry_datasets:
                if not include_datasets:
                    entry_dict['datasets'] = None
                else:
                    dataset_ids.update(entry_datasets)
        if include_datasets:
            bundle_info['datasets'] = [
                datamodel.Dataset.m_def.a_mongo.get(dataset_id=dataset_id).m_to_dict()
                for dataset_id in sorted(dataset_ids)]

        # Assemble the files
        file_source = self.upload_files.files_to_bundle(
            bundle_info, include_raw_files, include_archive_files)

        # Export
        if export_as_stream:
            return file_source.to_zipstream()
        elif zipped:
            file_source.to_zipfile(export_path, overwrite)
        else:
            file_source.to_disk(export_path, move_files, overwrite)
        return None

    @process()
    def import_bundle(
            self, bundle_path: str, move_files: bool = False, embargo_length: int = None,
            settings: config.NomadConfig = config.bundle_import.default_settings):
        '''
        A @process that imports data from an upload bundle to the current upload (which should
        normally have been created using the :func:`create_skeleton_from_bundle` method).
        Extensive checks are made to ensure referential consistency etc. Note, however,
        that no permission checks are done (the method does not check who is invoking the
        operation and if the user has the permissions to do so, this must be checked before
        calling this method).

        There are two ways to handle a failed bundle import: 1) leave the Upload object, files,
        etc. as they are, but ensure that nothing related to this upload is indexed in
        elastic search, or 2) delete everything, including the upload. This is determined
        by the setting `delete_upload_on_fail`.

        Arguments:
            bundle_path: The path to the bundle to import.
            move_files: If the files should be moved to the new location, rather than
                copied (only applicable if the bundle is created from a folder).
            embargo_length: Used to set the embargo length. If set to None, the value will be
                imported from the bundle. The value should be between 0 and 36. A value of
                0 means no embargo.
            settings: A dictionary structure defining how to import, see
                `config.import_bundle.default_settings` for available options. There,
                the default settings are also defined
        '''
        try:
            logger = self.get_logger(bundle_path=bundle_path)
            settings = config.bundle_import.default_settings.customize(settings)  # Add defaults
            bundle: UploadBundle = None
            new_datasets: List[datamodel.Dataset] = []
            entry_data_to_index: List[datamodel.EntryArchive] = []  # Data to index in ES
            bundle = UploadBundle(bundle_path)
            bundle_info = bundle.bundle_info
            # Sanity checks
            required_keys_root_level = (
                'upload_id', 'source.version', 'source.commit', 'source.deployment', 'source.deployment_id',
                'export_options.include_raw_files',
                'export_options.include_archive_files',
                'export_options.include_datasets',
                'upload._id', 'upload.main_author',
                'upload.upload_create_time', 'upload.process_status', 'upload.license',
                'upload.embargo_length',
                'entries')
            required_keys_entry_level = (
                '_id', 'upload_id', 'mainfile', 'parser_name', 'process_status', 'entry_create_time')
            required_keys_datasets = (
                'dataset_id', 'dataset_name', 'user_id')

            keys_exist(bundle_info, required_keys_root_level, 'Missing key in bundle_info.json: {key}')

            # Check version
            bundle_version = bundle_info['source']['version']
            assert bundle_version >= config.bundle_import.required_nomad_version, (
                'Bundle created in NOMAD version {}, required at least {}'.format(
                    bundle_version, config.bundle_import.required_nomad_version))

            if settings.include_raw_files:
                assert bundle_info['export_options']['include_raw_files'], (
                    'Raw files required but not included in the bundle')
            if settings.include_archive_files:
                assert bundle_info['export_options']['include_archive_files'], (
                    'Archive files required but not included in the bundle')
            if settings.include_datasets:
                assert bundle_info['export_options']['include_datasets'], (
                    'Datasets data required but not included in the bundle')

            upload_dict = bundle_info['upload']
            assert self.upload_id == bundle_info['upload_id'] == upload_dict['_id'], (
                'Inconsisten upload id information')
            published = upload_dict.get('publish_time') is not None
            if published:
                assert bundle_info['entries'], 'Upload published but no entries in bundle_info.json'
            # Check user references
            check_user_ids([upload_dict['main_author']], 'Invalid main_author: {id}')
            check_user_ids(upload_dict.get('coauthors', []), 'Invalid coauthor reference: {id}')
            check_user_ids(upload_dict.get('reviewers', []), 'Invalid reviewers reference: {id}')
            # Define which keys we think okay to copy from the bundle
            upload_keys_to_copy = [
                'upload_name', 'main_author', 'coauthors', 'reviewers', 'embargo_length', 'license',
                'from_oasis', 'oasis_deployment_id']
            if settings.keep_original_timestamps:
                upload_keys_to_copy.extend(('upload_create_time', 'publish_time',))
            try:
                # Update the upload with data from the json, and validate it
                update = {k: upload_dict[k] for k in upload_keys_to_copy if k in upload_dict}
                self.modify(**update)
                self.validate()
            except Exception as e:
                assert False, 'Bad upload json data: ' + str(e)
            current_time = datetime.utcnow()
            current_time_plus_tolerance = current_time + timedelta(minutes=2)
            if published and not settings.keep_original_timestamps:
                self.publish_time = current_time
            for timestamp in (self.upload_create_time, self.last_update, self.complete_time, self.publish_time):
                assert timestamp is None or timestamp < current_time_plus_tolerance, (
                    'Timestamp is in the future')
            if settings.set_from_oasis:
                self.from_oasis = True
                source_deployment_id = bundle_info['source']['deployment_id']
                assert source_deployment_id, 'No source deployment_id defined'
                if not self.oasis_deployment_id:
                    self.oasis_deployment_id = source_deployment_id
                    # Note, if oasis_deployment_id is set in the bundle_info, we keep this
                    # value as it is, since it indicates that the upload has been imported from
                    # somewhere else originally (i.e. source_deployment_id would not be the
                    # original source)

            # Dataset definitions
            if settings.include_datasets:
                assert 'datasets' in bundle_info, 'Missing datasets definition in bundle_info.json'
                datasets = bundle_info['datasets']
                dataset_id_mapping: Dict[str, str] = {}  # Map from old to new id (usually the same)
                for dataset_dict in datasets:
                    keys_exist(dataset_dict, required_keys_datasets, 'Missing key in dataset definition: {key}')
                    check_user_ids([dataset_dict['user_id']], 'Invalid dataset creator id: {id}')
                    dataset_id = dataset_dict['dataset_id']
                    try:
                        existing_dataset = datamodel.Dataset.m_def.a_mongo.get(
                            user_id=dataset_dict['user_id'],
                            dataset_name=dataset_dict['dataset_name'])
                        # Dataset by the given dataset_name and user_id already exists
                        dataset_id_mapping[dataset_id] = existing_dataset.dataset_id
                        # Note, it may be that a dataset with the same dataset_name and creator
                        # is created in both environments. In that case, we consider them
                        # to be the "same" dataset, even if they do not have the same dataset_id.
                        # Thus, in that case the dataset id needs to be translated.
                        assert not existing_dataset.doi, (
                            f'Matched dataset {existing_dataset.dataset_id} has a DOI, cannot be updated')
                    except KeyError:
                        # Completely new dataset, create it
                        new_dataset = datamodel.Dataset(**dataset_dict)
                        new_dataset.a_mongo.save()
                        new_datasets.append(new_dataset)
                        dataset_id_mapping[dataset_id] = dataset_id
            # Entries
            entries = []
            for entry_dict in bundle_info['entries']:
                keys_exist(entry_dict, required_keys_entry_level, 'Missing key for entry: {key}')
                assert entry_dict['process_status'] in ProcessStatus.STATUSES_NOT_PROCESSING, (
                    f'Invalid entry `process_status`')
                # Check referential consistency
                assert entry_dict['upload_id'] == self.upload_id, (
                    'Mismatching upload_id in entry definition')
                assert entry_dict['_id'] == generate_entry_id(self.upload_id, entry_dict['mainfile']), (
                    'Provided entry id does not match generated value')
                check_user_ids(entry_dict.get('entry_coauthors', []), 'Invalid entry_coauthor reference: {id}')

                # Instantiate an entry object from the json, and validate it
                entry_keys_to_copy = list(_mongo_entry_metadata)
                entry_keys_to_copy.extend((
                    'upload_id', 'errors', 'warnings', 'last_status_message',
                    'current_process', 'complete_time', 'worker_hostname', 'celery_task_id'))
                try:
                    update = {k: entry_dict[k] for k in entry_keys_to_copy if k in entry_dict}
                    update['calc_id'] = entry_dict['_id']
                    if not settings.keep_original_timestamps:
                        update['entry_create_time'] = current_time
                    entry: Calc = Calc.create(**update)
                    entry.process_status = entry_dict['process_status']
                    entry.validate()
                except Exception as e:
                    assert False, 'Bad entry json data: ' + str(e)
                # Instantiate an EntryMetadata object to validate the format
                try:
                    if settings.include_datasets:
                        entry_datasets = entry_dict.get('datasets')
                        if entry_datasets:
                            entry.datasets = [
                                dataset_id_mapping[id] for id in entry_datasets] or None
                    else:
                        entry.datasets = None
                    entry.mongo_metadata(self)
                    # TODO: if we don't import archive files, should we still index something in ES?
                except Exception as e:
                    assert False, 'Invalid entry metadata: ' + str(e)
                entries.append(entry)

            # Validate embargo settings
            if embargo_length is not None:
                self.embargo_length = embargo_length  # Importing with different embargo
            assert type(self.embargo_length) == int and 0 <= self.embargo_length <= 36, (
                'Invalid embargo_length, must be between 0 and 36 months')

            # Import the files
            bundle.import_upload_files(
                settings.include_raw_files, settings.include_archive_files, settings.include_bundle_info,
                move_files)

            if self.published and embargo_length is not None:
                # Repack the upload
                PublicUploadFiles(self.upload_id).re_pack(with_embargo=self.with_embargo)

            # Check the archive metadata, if included
            if settings.include_archive_files:
                for entry in entries:
                    try:
                        entry_metadata = entry.full_entry_metadata(self)
                        entry_data_to_index.append(
                            cast(datamodel.EntryArchive, entry_metadata.m_parent))
                        # TODO: Should we validate the entire ArchiveObject, not just the indexed data?
                    except Exception as e:
                        assert False, 'Invalid metadata in archive entry: ' + str(e)
            self.upload_files.close()  # Because full_entry_metadata reads the archive files.

            # Everything looks good - save to mongo.
            self.save()
            for entry in entries:
                entry.save()

            # Index in elastic search
            if entry_data_to_index:
                search.index(
                    entry_data_to_index, update_materials=config.process.index_materials,
                    refresh=True)

            if settings.trigger_processing:
                reprocess_settings = {
                    k: v for k, v in settings.items() if k in config.reprocess}
                return self._process_upload_local(reprocess_settings=reprocess_settings)

        except Exception as e:
            if settings.get('delete_upload_on_fail'):
                # Delete everything
                self.delete_upload_local()  # Will also delete files, entries and remove from elastic search
                if new_datasets:
                    for dataset in new_datasets:
                        dataset.a_mongo.delete()
                return ProcessStatus.DELETED
            else:
                # Just ensure the upload is deleted from search
                with utils.timer(logger, 'upload deleted from index'):
                    search.delete_upload(self.upload_id, refresh=True)
                raise

        finally:
            if bundle:
                bundle.close()
                if settings.get('delete_bundle_when_done'):
                    bundle.delete(settings.get('also_delete_bundle_parent_folder', False))

    def __str__(self):
        return 'upload %s upload_id%s' % (super().__str__(), self.upload_id)
