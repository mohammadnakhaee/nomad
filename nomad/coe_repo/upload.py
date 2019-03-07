# Copyright 2018 Markus Scheidgen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an"AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Interface to the NOMAD-coe repository postgres database. This implementation is based on
SQLAlchemy. There are model classes that represent entries in the *users* and *session*
tables.

This module allows to authenticate users based on user password or session tokens.
It allows to access the user data like names and user_id.

.. autoclass:: User
    :members:
    :undoc-members:

.. autoclass:: Session
    :members:
    :undoc-members:

.. autofunction:: ensure_test_user

This module also provides functionality to add parsed calculation data to the db:

.. autoclass:: UploadMetaData
    :members:
.. autoclass:: Upload
    :members:
    :undoc-members:
.. autoclass:: Calc
    :members:
    :undoc-members:
"""

from typing import Type
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import filelock
import os.path

from nomad import utils, infrastructure, config
from nomad.datamodel import UploadWithMetadata

from .calc import Calc, PublishContext
from .base import Base
from .user import User


class UploadMetaData:
    """
    Utility class that provides per upload meta data and overriding per calculation
    meta data. For a given *mainfile* data is first read from the `calculations` key
    (a list of calculation dict with a matching `mainfile` key), before it is read
    from `metadata_dict` it self.

    The class is used to deal with user provided meta-data.

    Arguments:
        metadata_dict: The python dict with the meta-data.
    """
    def __init__(self, metadata_dict: dict) -> None:
        self._upload_data = metadata_dict
        self._calc_data: dict = {
            calc['mainfile']: calc
            for calc in self._upload_data.get('calculations', [])}

    def get(self, mainfile: str) -> dict:
        return self._calc_data.get(mainfile, self._upload_data)


class Upload(Base):  # type: ignore
    __tablename__ = 'uploads'

    coe_upload_id = Column('upload_id', Integer, primary_key=True, autoincrement=True)
    upload_name = Column(String)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    is_processed = Column(Boolean)
    created = Column(DateTime)

    user = relationship('User')
    calcs = relationship('Calc', lazy='subquery')

    @staticmethod
    def from_upload_id(upload_id: str) -> 'Upload':
        repo_db = infrastructure.repository_db
        uploads = repo_db.query(Upload).filter_by(upload_name=upload_id)
        assert uploads.count() <= 1, 'Upload id/name must be unique'
        return uploads.first()

    @property
    def upload_id(self) -> str:
        return self.upload_name

    @property
    def uploader(self) -> User:
        return self.user

    @property
    def upload_time(self) -> Type[datetime.datetime]:
        return self.created

    @staticmethod
    def publish(upload: UploadWithMetadata) -> int:
        """
        Add the upload to the NOMAD-coe repository db. It creates an
        uploads-entry, respective calculation and property entries. Everything in one
        transaction.

        Arguments:
            upload: The upload to add, including calculations with respective IDs, UMD, CMD.

        Returns: A callback that allows to commit or rollback the publish transaction.
            The callback returns the ``coe_upload_id`` or -1, if rolledback or no upload
            was created, due to no calcs in the upload.
        """
        assert upload.uploader is not None

        logger = utils.get_logger(__name__, upload_id=upload.upload_id)

        last_error = None

        while True:
            publish_filelock = filelock.FileLock(
                os.path.join(config.fs.tmp, 'publish.lock'))
            logger.info('waiting for filelock')
            while True:
                try:
                    publish_filelock.acquire(timeout=15 * 60, poll_intervall=1)
                    logger.info('acquired filelock')
                    break
                except filelock.Timeout:
                    logger.warning('could not acquire publish lock after generous timeout')

            repo_db = infrastructure.repository_db
            repo_db.expunge_all()
            repo_db.begin()

            try:
                has_calcs = False

                # create upload
                coe_upload = Upload(
                    upload_name=upload.upload_id,
                    created=upload.upload_time,
                    user_id=upload.uploader.id,
                    is_processed=True)
                repo_db.add(coe_upload)

                # add calculations and metadata
                # reuse the cache for the whole transaction to profit from repeating
                # star schema entries for users, ds, topics, etc.
                context = PublishContext(upload_id=upload.upload_id)
                for calc in upload.calcs:
                    has_calcs = True
                    coe_calc = Calc(
                        coe_calc_id=calc.pid,
                        checksum=calc.calc_id,
                        upload=coe_upload)
                    repo_db.add(coe_calc)

                    coe_calc.apply_calc_with_metadata(calc, context=context)
                    logger.debug(
                        'added calculation, not yet committed', calc_id=coe_calc.calc_id)

                logger.info('filled publish transaction')

                upload_id = -1
                if has_calcs:
                    repo_db.commit()
                    logger.info('committed publish transaction')
                    upload_id = coe_upload.coe_upload_id
                else:
                    # empty upload case
                    repo_db.rollback()
                    return -1

                logger.info('added upload')
                return upload_id
            except Exception as e:
                repo_db.rollback()
                if last_error != str(e):
                    last_error = str(e)
                    logger.error('Retry publish after unexpected execption.', exc_info=e)
                else:
                    logger.error('Unexpected exception.', exc_info=e)
                    raise e
            finally:
                publish_filelock.release()
                logger.info('released filelock')