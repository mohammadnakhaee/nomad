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
Definitions that are used in the documentation via mkdocs-macro-plugin.
'''

from nomad.app.v1.models import (
    query_documentation,
    owner_documentation)
from nomad.app.v1.routers.entries import archive_required_documentation
from nomad import utils

import yaml
import json
import os.path


doc_snippets = {
    'query': query_documentation,
    'owner': owner_documentation,
    'archive-required': archive_required_documentation
}


class MyYamlDumper(yaml.Dumper):
    '''
    A custom dumper that always shows objects in yaml and not json syntax
    even with default_flow_style=None.
    '''
    def represent_mapping(self, *args, **kwargs):
        node = super(MyYamlDumper, self).represent_mapping(*args, **kwargs)
        node.flow_style = False
        return node


def define_env(env):
    @env.macro
    def nomad_url():  # pylint: disable=unused-variable
        # TODO Fix the configuration during build time.
        return 'https://nomad-lab.eu/prod/v1/staging/api'
        # return config.api_url()

    @env.macro
    def doc_snippet(key):  # pylint: disable=unused-variable
        return doc_snippets[key]

    @env.macro
    def metainfo_data():  # pylint: disable=unused-variable
        return utils.strip('''
            You can browse the [NOMAD metainfo schema](../gui/analyze/metainfo)
            or the archive of each entry (e.g. [a VASP example](../gui/search/entries/entry/id/d5OYC0SJTDevHMPk7YHd4A/-7j8ojKkna2NLXdytv_OjV4zsBXw/archive))
            in the web-interface.''')

    @env.macro
    def get_schema_doc(key):  # pylint: disable=unused-variable
        schema_yaml = './docs/schema/suggestions.yaml'
        with open(schema_yaml, "r") as yaml_file:
            try:
                schema = yaml.safe_load(yaml_file)
            except yaml.YAMLError as exc:
                print(exc)

        items = schema[key]
        md_table = ['|Key|Description|', '|---|---|']
        for item, description in items.items():
            if key == 'type' and (item == 'log' or item == 'scatter'):
                continue
            md_table.append('|{}|{}|'.format(str(item), str(description)))
        return utils.strip('\n'.join(md_table))

    @env.macro
    def yaml_snippet(path, indent, filter=None):  # pylint: disable=unused-variable
        '''
        Produces a yaml string from a (partial) .json or .yaml file.

        Arguments:
            path: The path to the file relative to project root.
            indent: Additional indentation that is added to each line of the result string.
            filter:
                Optional comma separated list of keys that should be removed from
                the top-level object.
        '''

        if ':' not in path:
            path = f'{path}:'

        file_path, json_path = path.split(':')
        file_path = os.path.join(os.path.dirname(__file__), '..', file_path)

        with open(file_path, 'rt') as f:
            if file_path.endswith('.yaml'):
                data = yaml.load(f, Loader=yaml.FullLoader)
            elif file_path.endswith('.json'):
                data = json.load(f)
            else:
                raise NotImplementedError('Only .yaml and .json is supported')

        for segment in json_path.split('/'):
            if segment == '':
                continue
            try:
                segment = int(segment)
            except ValueError:
                pass
            data = data[segment]

        if filter is not None:
            filter = set([item.strip() for item in filter.split(',')])
            to_remove = []
            for key in data.keys():
                if key in filter:
                    to_remove.append(key)
            for key in to_remove:
                del(data[key])

        yaml_string = yaml.dump(
            data,
            sort_keys=False, default_flow_style=None,
            Dumper=MyYamlDumper)
        return f'\n{indent}'.join(f'{indent}{yaml_string}'.split('\n'))
