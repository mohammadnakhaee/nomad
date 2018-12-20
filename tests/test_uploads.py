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

from typing import Generator, Any, Dict
import os
import os.path
import shutil
import pytest

from nomad import config
from nomad.uploads import DirectoryObject, PathObject
from nomad.uploads import Metadata, MetadataTimeout, PublicMetadata, StagingMetadata
from nomad.uploads import StagingUploadFiles, PublicUploadFiles, UploadFiles, Restricted

from tests.test_files import example_file, example_file_contents, example_file_mainfile


class TestObjects:

    @pytest.fixture(scope='function')
    def test_bucket(self):
        yield 'test_bucket'

        bucket = os.path.join(config.fs.objects, 'test_bucket')
        if os.path.exists(bucket):
            shutil.rmtree(os.path.join(config.fs.objects, 'test_bucket'))

    def test_file_dir_existing(self, test_bucket):
        file = PathObject(test_bucket, 'sub/test_id')
        assert not os.path.exists(os.path.dirname(file.os_path))

    @pytest.mark.parametrize('dirpath', ['test', os.path.join('sub', 'test')])
    @pytest.mark.parametrize('create', [True, False])
    @pytest.mark.parametrize('prefix', [True, False])
    def test_directory(self, test_bucket: str, dirpath: str, create: bool, prefix: bool) -> None:
        directory = DirectoryObject(test_bucket, dirpath, create=create, prefix=prefix)
        assert directory.exists() == create
        assert os.path.isdir(directory.os_path) == create
        assert directory.os_path.endswith(os.path.join('tes' if prefix else '', 'test'))

    @pytest.mark.parametrize('dirpath', ['test', os.path.join('sub', 'test')])
    @pytest.mark.parametrize('create', [True, False])
    @pytest.mark.parametrize('join_create', [True, False])
    @pytest.mark.parametrize('prefix', [True, False])
    def test_directory_join(self, test_bucket: str, dirpath: str, create: bool, prefix: bool, join_create: bool) -> None:
        directory = DirectoryObject(test_bucket, 'parent', create=create, prefix=prefix)
        directory = directory.join_dir(dirpath, create=join_create)

        assert directory.exists() == join_create
        assert os.path.isdir(directory.os_path) == join_create
        assert dirpath.endswith(os.path.join('', 'test'))

    @pytest.mark.parametrize('filepath', ['test', 'sub/test'])
    @pytest.mark.parametrize('create', [True, False])
    def test_directory_join_file_dir_create(self, test_bucket: str, filepath: str, create: bool):
        directory = DirectoryObject(test_bucket, 'parent', create=create)
        file = directory.join_file(filepath)
        assert os.path.exists(directory.os_path) == create
        assert os.path.exists(os.path.dirname(file.os_path)) == create


example_calc: Dict[str, Any] = {
    'hash': '0',
    'mainfile': 'examples_template/template.json',
    'data': 'value'
}
example_calc_hash = example_calc['hash']


def assert_example_calc(calc):
    assert calc is not None
    assert calc['data'] == example_calc['data']


class MetadataContract:
    @pytest.fixture(scope='function')
    def test_dir(self):
        path = os.path.join(config.fs.tmp, 'test_dir')
        os.makedirs(path)
        yield path
        shutil.rmtree(path)

    @pytest.fixture(scope='function')
    def md(self, test_dir):
        raise NotImplementedError()

    def test_open_empty(self, md):
        pass

    def test_insert(self, md: Metadata):
        md.insert(example_calc)
        assert len(md) == 1
        assert_example_calc(md.get(example_calc_hash))

    def test_insert_fail(self, md: Metadata):
        failed = False
        md.insert(example_calc)
        try:
            md.insert(example_calc)
        except Exception:
            failed = True

        assert failed
        assert len(md) == 1

    def test_update(self, md: Metadata):
        md.insert(example_calc)
        md.update(example_calc_hash, dict(data='updated'))
        assert len(md) == 1
        assert md.get(example_calc_hash)['data'] == 'updated'

    def test_update_fail(self, md: Metadata):
        failed = False
        try:
            md.update(example_calc_hash, dict(data='updated'))
        except KeyError:
            failed = True
        assert failed
        assert len(md) == 0

    def test_get(self, md: Metadata):
        md.insert(example_calc)
        assert_example_calc(md.get(example_calc_hash))

    def test_get_fail(self, md: Metadata):
        failed = False
        try:
            md.get(example_calc_hash)
        except KeyError:
            failed = True
        assert failed


class TestStagingMetadata(MetadataContract):
    @pytest.fixture(scope='function')
    def md(self, test_dir):
        with StagingMetadata(DirectoryObject(None, None, os_path=test_dir)) as md:
            yield md


class TestPublicMetadata(MetadataContract):

    @pytest.fixture(scope='function')
    def md(self, test_dir):
        with PublicMetadata(test_dir) as md:
            yield md

    def test_lock(self, test_dir):
        timeout = False
        with PublicMetadata(test_dir):
            try:
                with PublicMetadata(test_dir, lock_timeout=0.1):
                    pass
            except MetadataTimeout:
                timeout = True
        assert timeout


class UploadFilesContract:

    @pytest.fixture(scope='function')
    def test_upload_id(self) -> Generator[str, None, None]:
        yield 'test_upload'
        for bucket in [config.files.staging_bucket, config.files.public_bucket]:
            directory = DirectoryObject(bucket, 'test_upload', prefix=True)
            if directory.exists():
                directory.delete()

    @pytest.fixture(scope='function', params=['r'])
    def test_upload(self, request, test_upload_id) -> UploadFiles:
        raise NotImplementedError()

    @pytest.fixture(scope='function')
    def empty_test_upload(self, test_upload_id) -> Generator[UploadFiles, None, None]:
        raise NotImplementedError()

    def test_create(self, empty_test_upload):
        pass

    def test_rawfile(self, test_upload):
        try:
            with test_upload.raw_file(example_file_mainfile) as f:
                assert len(f.read()) > 0
            if test_upload.public_only:
                with test_upload.metadata as md:
                    assert not md.get(example_calc_hash).get('restricted', False)
        except Restricted:
            assert test_upload.public_only
            with test_upload.metadata as md:
                assert md.get(example_calc_hash).get('restricted', False)

    def test_archive(self, test_upload):
        try:
            with test_upload.archive_file(example_calc_hash) as f:
                assert f.read() == b'archive'
            if test_upload.public_only:
                with test_upload.metadata as md:
                    assert not md.get(example_calc_hash).get('restricted', False)
        except Restricted:
            assert test_upload.public_only
            with test_upload.metadata as md:
                assert md.get(example_calc_hash).get('restricted', False)

    def test_metadata(self, test_upload):
        with test_upload.metadata as md:
            assert_example_calc(md.get(example_calc_hash))

    def test_update_metadata(self, test_upload):
        with test_upload.metadata as md:
            md.update(example_calc_hash, dict(data='updated'))

        with test_upload.metadata as md:
            assert md.get(example_calc_hash)['data'] == 'updated'


class TestStagingUploadFiles(UploadFilesContract):

    @staticmethod
    def create_upload(upload_id: str, calc_specs: str) -> StagingUploadFiles:
        """
        Create an upload according to given calc_specs. Where calc specs is a string
        with letters determining example calcs being public or restricted.
        The calcs will be copies of example_calc. First calc is at top level, following
        calcs will be put under 1/, 2/, etc.
        """
        upload = StagingUploadFiles(upload_id, create=True, archive_ext='txt', public_only=False)

        prefix = 0
        for calc_spec in calc_specs:
            upload.add_rawfiles(example_file, prefix=None if prefix == 0 else str(prefix))
            hash = str(int(example_calc_hash) + prefix)
            with upload.archive_file(hash, read=False) as f:
                f.write(b'archive')
            calc = dict(**example_calc)
            calc['hash'] = hash
            if prefix > 0:
                calc['mainfile'] = os.path.join(str(prefix), calc['mainfile'])
            if calc_spec == 'r':
                calc['restricted'] = True
            elif calc_spec == 'p':
                calc['restricted'] = False
            upload.metadata.insert(calc)
            prefix += 1

        if calc_specs.startswith('P'):
            public_only = True
            calc_specs = calc_specs[1:]
        else:
            public_only = False
        upload.public_only = public_only

        with upload.metadata as md:
            assert len(md) == len(calc_specs)
        return upload

    @pytest.fixture(scope='function', params=['r', 'rr', 'pr', 'rp', 'p', 'pp'])
    def test_upload(self, request, test_upload_id: str) -> StagingUploadFiles:
        return TestStagingUploadFiles.create_upload(test_upload_id, calc_specs=request.param)

    @pytest.fixture(scope='function')
    def empty_test_upload(self, test_upload_id) -> Generator[UploadFiles, None, None]:
        yield StagingUploadFiles(test_upload_id, create=True, public_only=False)

    @pytest.mark.parametrize('prefix', [None, 'prefix'])
    def test_add_rawfiles_zip(self, test_upload_id, prefix):
        test_upload = StagingUploadFiles(test_upload_id, create=True, archive_ext='txt', public_only=False)
        test_upload.add_rawfiles(example_file, prefix=prefix)
        for filepath in example_file_contents:
            filepath = os.path.join(prefix, filepath) if prefix else filepath
            with test_upload.raw_file(filepath) as f:
                content = f.read()
                if filepath == example_file_mainfile:
                    assert len(content) > 0

    def test_write_archive(self, test_upload):
        with test_upload.archive_file(example_calc_hash) as f:
            assert f.read() == b'archive'

    def test_calc_hash(self, test_upload):
        assert test_upload.calc_hash(example_file_mainfile) is not None

    def test_pack(self, test_upload):
        test_upload.pack()

    def test_all_rawfiles(self, test_upload: StagingUploadFiles):
        for filepath in test_upload.all_rawfiles:
            assert os.path.isfile(filepath)

    def test_calc_files(self, test_upload: StagingUploadFiles):
        for calc in test_upload.metadata:
            mainfile = calc['mainfile']
            calc_files = test_upload.calc_files(mainfile)
            assert len(list(calc_files)) == len(example_file_contents)
            for one, two in zip(calc_files, sorted(example_file_contents)):
                assert one.endswith(two)
                assert one.startswith(mainfile[:3])


class TestPublicUploadFiles(UploadFilesContract):

    @pytest.fixture(scope='function')
    def empty_test_upload(self, test_upload_id: str) -> Generator[UploadFiles, None, None]:
        yield PublicUploadFiles(test_upload_id, archive_ext='txt', public_only=False)

    @pytest.fixture(scope='function', params=['r', 'rr', 'pr', 'rp', 'p', 'pp', 'Ppr', 'Prp'])
    def test_upload(self, request, test_upload_id: str) -> PublicUploadFiles:
        calc_specs = request.param
        if calc_specs.startswith('P'):
            public_only = True
            calc_specs = calc_specs[1:]
        else:
            public_only = False

        staging_upload = TestStagingUploadFiles.create_upload(test_upload_id, calc_specs=calc_specs)
        staging_upload.pack()
        return PublicUploadFiles(test_upload_id, archive_ext='txt', public_only=public_only)
