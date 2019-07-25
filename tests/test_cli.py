
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

import click.testing
import json

from nomad import utils, search, processing as proc
from nomad.cli import cli
from nomad.processing import Upload, Calc


# TODO there is much more to test

class TestAdmin:
    def test_clean(self, published, no_warn, reset_config):
        upload_id = published.upload_id

        Upload.objects(upload_id=upload_id).delete()
        assert published.upload_files.exists()
        assert Calc.objects(upload_id=upload_id).first() is not None
        assert search.entry_search(search_parameters=dict(upload_id=upload_id))['pagination']['total'] > 0

        result = click.testing.CliRunner().invoke(
            cli, ['admin', 'clean', '--force', '--skip-es'], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert not published.upload_files.exists()
        assert Calc.objects(upload_id=upload_id).first() is None
        assert search.entry_search(search_parameters=dict(upload_id=upload_id))['pagination']['total'] > 0


class TestAdminUploads:

    def test_ls(self, published, no_warn, reset_config):
        upload_id = published.upload_id

        result = click.testing.CliRunner().invoke(
            cli, ['admin', 'uploads', 'ls', upload_id], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert '1 uploads selected' in result.stdout

    def test_rm(self, published, no_warn, reset_config):
        upload_id = published.upload_id

        result = click.testing.CliRunner().invoke(
            cli, ['admin', 'uploads', 'rm', upload_id], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert 'deleting' in result.stdout
        assert Upload.objects(upload_id=upload_id).first() is None
        assert Calc.objects(upload_id=upload_id).first() is None

    def test_re_process(self, published, no_warn, monkeypatch, reset_config):
        monkeypatch.setattr('nomad.config.version', 'test_version')
        upload_id = published.upload_id
        calc = Calc.objects(upload_id=upload_id).first()
        assert calc.metadata['nomad_version'] != 'test_version'

        result = click.testing.CliRunner().invoke(
            cli, ['admin', 'uploads', 're-process', '--parallel', '2', upload_id], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert 're-processing' in result.stdout
        calc.reload()
        assert calc.metadata['nomad_version'] == 'test_version'


class TestClient:

    def test_mirror_dry(self, published, admin_user_bravado_client):
        result = click.testing.CliRunner().invoke(
            cli, ['client', 'mirror', '--dry'], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert published.upload_id in result.output
        assert published.upload_files.os_path in result.output

    def test_mirror(self, published, admin_user_bravado_client, monkeypatch):
        ref_search_results = search.entry_search(
            search_parameters=dict(upload_id=published.upload_id))['results'][0]

        monkeypatch.setattr('nomad.cli.client.mirror.__in_test', True)

        result = click.testing.CliRunner().invoke(
            cli, ['client', 'mirror'], catch_exceptions=False, obj=utils.POPO())

        assert result.exit_code == 0
        assert proc.Upload.objects(upload_id=published.upload_id).count() == 1
        assert proc.Calc.objects(upload_id=published.upload_id).count() == 1
        new_search = search.entry_search(search_parameters=dict(upload_id=published.upload_id))
        calcs_in_search = new_search['pagination']['total']
        assert calcs_in_search == 1

        new_search_results = new_search['results'][0]
        for key in new_search_results.keys():
            if key not in ['upload_time']:  # There is a sub second change due to date conversions (?)
                assert json.dumps(new_search_results[key]) == json.dumps(ref_search_results[key])

        published.upload_files.exists
