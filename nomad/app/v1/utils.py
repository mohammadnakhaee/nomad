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

from typing import Dict, Set, Iterator, Any, Optional, Union
from types import FunctionType
import urllib
import io
import json
import os
import sys
import inspect
from fastapi import Request, Query, HTTPException  # pylint: disable=unused-import
from pydantic import ValidationError, BaseModel  # pylint: disable=unused-import
import zipstream
from nomad.files import UploadFiles

if sys.version_info >= (3, 7):
    import zipfile
else:
    import zipfile37 as zipfile  # pragma: no cover


def parameter_dependency_from_model(name: str, model_cls):
    '''
    Takes a pydantic model class as input and creates a dependency with corresponding
    Query parameter definitions that can be used for GET
    requests.

    This will only work, if the fields defined in the input model can be turned into
    suitable query parameters. Otherwise fastapi will complain down the road.

    Arguments:
        name: Name for the dependency function.
        model_cls: A ``BaseModel`` inheriting model class as input.
    '''
    names = []
    annotations: Dict[str, type] = {}
    defaults = []
    for field_model in model_cls.__fields__.values():
        field_info = field_model.field_info

        names.append(field_model.name)
        annotations[field_model.name] = field_model.outer_type_
        defaults.append(Query(field_model.default, description=field_info.description))

    code = inspect.cleandoc('''
    def %s(%s):
        try:
            return %s(%s)
        except ValidationError as e:
            errors = e.errors()
            for error in errors:
                error['loc'] = ['query'] + list(error['loc'])
            raise HTTPException(422, detail=errors)

    ''' % (
        name, ', '.join(names), model_cls.__name__,
        ', '.join(['%s=%s' % (name, name) for name in names])))

    compiled = compile(code, 'string', 'exec')
    env = {model_cls.__name__: model_cls}
    env.update(**globals())
    func = FunctionType(compiled.co_consts[0], env, name)
    func.__annotations__ = annotations
    func.__defaults__ = (*defaults,)

    return func


class File(BaseModel):
    path: str
    f: Any
    size: int


def create_streamed_zipfile(
        files: Iterator[File],
        compress: bool = False) -> Iterator[bytes]:

    '''
    Creates a streaming zipfile object that can be used in fastapi's ``StreamingResponse``.
    '''

    def path_to_write_generator():
        for file_obj in files:
            def content_generator():
                while True:
                    data = file_obj.f.read(1024 * 64)
                    if not data:
                        break
                    yield data

            yield dict(
                arcname=file_obj.path,
                iterable=content_generator(),
                buffer_size=file_obj.size)

    compression = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    zip_stream = zipstream.ZipFile(mode='w', compression=compression, allowZip64=True)
    zip_stream.paths_to_write = path_to_write_generator()

    for chunk in zip_stream:
        yield chunk


class DownloadItem(BaseModel):
    ''' Defines an object (file or folder) for download. '''
    upload_id: str
    is_authorized: bool
    raw_path: str
    zip_path: str
    entry_metadata: Optional[Dict[str, Any]]


def create_download_stream_zipped(
        download_items: Union[DownloadItem, Iterator[DownloadItem]],
        upload_files: UploadFiles = None,
        re_pattern: Any = None,
        recursive: bool = False,
        create_manifest_file: bool = False,
        compress: bool = True) -> Iterator[bytes]:
    '''
    Creates a zip-file stream for downloading raw data with ``StreamingResponse``.

    Arguments:
        download_items: A DownloadItem, or iterator of DownloadItems, defining what to download.
        upload_files: The UploadFiles object, if already opened (for optimiztion).
        re_pattern: A regex object for filtering by filenames (only applicable to directories).
        recursive: if subdirectories should be included (recursively).
        create_manifest_file: if set, a manifest file is created in the root folder.
        compress: if the zip file should be compressed or not
    '''
    def file_generator(upload_files) -> Iterator[File]:
        manifest = []
        try:
            items: Iterator[DownloadItem] = (
                iter([download_items]) if isinstance(download_items, DownloadItem)
                else download_items)
            streamed_paths: Set[str] = set()

            for download_item in items:
                if upload_files and upload_files.upload_id != download_item.upload_id:
                    # We're switching to a new upload. Close the old.
                    upload_files.close()
                    upload_files = None
                if not upload_files:
                    # Open the requested upload.
                    upload_files = UploadFiles.get(
                        download_item.upload_id,
                        is_authorized=lambda *args, **kwargs: download_item.is_authorized)

                all_filtered = True
                files_found = False
                if not upload_files.raw_path_exists(download_item.raw_path):
                    pass
                elif upload_files.raw_path_is_file(download_item.raw_path):
                    # File
                    if download_item.zip_path not in streamed_paths:
                        streamed_paths.add(download_item.zip_path)
                        yield File(
                            path=download_item.zip_path,
                            f=upload_files.raw_file(download_item.raw_path, 'rb'),
                            size=upload_files.raw_file_size(download_item.raw_path))
                else:
                    # Directory
                    for path_info in upload_files.raw_directory_list(
                            download_item.raw_path, recursive, files_only=True):
                        files_found = True
                        if not re_pattern or re_pattern.search(path_info.path):
                            all_filtered = False
                            relative_path = os.path.relpath(path_info.path, download_item.raw_path)
                            zip_path = os.path.join(download_item.zip_path, relative_path)
                            if zip_path not in streamed_paths:
                                streamed_paths.add(zip_path)
                                yield File(
                                    path=zip_path,
                                    f=upload_files.raw_file(path_info.path, 'rb'),
                                    size=path_info.size)

                if create_manifest_file and download_item.entry_metadata:
                    if not all_filtered or not files_found:
                        manifest.append(download_item.entry_metadata)

            if create_manifest_file:
                manifest_content = json.dumps(manifest).encode()
                yield File(path='manifest.json', f=io.BytesIO(manifest_content), size=len(manifest_content))

        finally:
            if upload_files:
                upload_files.close()

    return create_streamed_zipfile(file_generator(upload_files), compress=compress)


def create_download_stream_raw_file(upload_files: UploadFiles, path: str) -> Iterator[bytes]:
    '''
    Creates a file stream for downloading raw data with ``StreamingResponse``.

    Arguments:
        upload_files: the UploadFiles object, containing the file. Will be closed when done.
        path: the raw path within the upload to the desired file.
    '''
    raw_file = upload_files.raw_file(path, 'rb')
    for chunk in raw_file:
        yield chunk
    raw_file.close()
    upload_files.close()


def create_stream_from_string(content: str) -> Iterator[bytes]:
    ''' For returning strings as content using '''
    yield content.encode()


def create_responses(*args):
    return {
        status_code: response
        for status_code, response in args}


def update_url_query_arguments(original_url: str, **kwargs) -> str:
    '''
    Takes an url, and returns a new url, obtained by updating the query arguments in the
    `original_url` as specified by the kwargs.
    '''
    scheme, netloc, path, params, query, fragment = urllib.parse.urlparse(original_url)
    query_dict = urllib.parse.parse_qs(query)
    for k, v in kwargs.items():
        if v is None:
            # Unset the value
            if k in query_dict:
                query_dict.pop(k)
        else:
            query_dict[k] = [str(v)]
    query = urllib.parse.urlencode(query_dict, doseq=True)
    return urllib.parse.urlunparse((scheme, netloc, path, params, query, fragment))
