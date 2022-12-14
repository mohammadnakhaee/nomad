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
This module describes all configurable parameters for the nomad python code. The
configuration is used for all executed python code including API, worker, CLI, and other
scripts. To use the configuration in your own scripts or new modules, simply import
this module.

All parameters are structured into objects for two reasons. First, to have
categories. Second, to allow runtime manipulation that is not effected
by python import logic. The categories are choosen along infrastructure components:
``mongo``, ``elastic``, etc.

This module also provides utilities to read the configuration from environment variables
and .yaml files. This is done automatically on import. The precedence is env over .yaml
over defaults.

.. autoclass:: nomad.config.NomadConfig
.. autofunction:: nomad.config.load_config
'''

import logging
import os
import inspect
import os.path
import yaml
import warnings
from typing import Dict, List, Any
from pkg_resources import get_distribution, DistributionNotFound

try:
    __version__ = get_distribution("nomad-lab").version
except DistributionNotFound:
    # package is not installed
    pass


warnings.filterwarnings('ignore', message='numpy.dtype size changed')
warnings.filterwarnings('ignore', message='numpy.ufunc size changed')
warnings.filterwarnings('ignore', category=DeprecationWarning)


class NomadConfig(dict):
    '''
    A class for configuration categories. It is a dict subclass that uses attributes as
    key/value pairs.
    '''
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: " + name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError("No such attribute: " + name)

    def customize(self, custom_settings: Dict[str, Any]) -> 'NomadConfig':
        '''
        Returns a new NomadConfig object, created by taking a copy of the current config and
        updating it with the settings defined in `custom_settings`. The `custom_settings` dict
        must not contain any new keys (keys not defined in this NomadConfig). If it does,
        an exception will be raised.
        '''
        rv = NomadConfig(**self)
        if custom_settings:
            for k, v in custom_settings.items():
                assert k in rv, f'Invalid setting: {k}'
                rv[k] = v
        return rv


CELERY_WORKER_ROUTING = 'worker'
CELERY_QUEUE_ROUTING = 'queue'

rabbitmq = NomadConfig(
    host='localhost',
    user='rabbitmq',
    password='rabbitmq'
)


def rabbitmq_url():
    return 'pyamqp://%s:%s@%s//' % (rabbitmq.user, rabbitmq.password, rabbitmq.host)


celery = NomadConfig(
    max_memory=64e6,  # 64 GB
    timeout=1800,  # 1/2 h
    acks_late=False,
    routing=CELERY_QUEUE_ROUTING,
    priorities={
        'Upload.process_upload': 5,
        'Upload.delete_upload': 9,
        'Upload.publish_upload': 10
    }
)

fs = NomadConfig(
    tmp='.volumes/fs/tmp',
    staging='.volumes/fs/staging',
    staging_external=None,
    public='.volumes/fs/public',
    public_external=None,
    local_tmp='/tmp',
    prefix_size=2,
    archive_version_suffix='v1',
    working_directory=os.getcwd(),
    external_working_directory=None
)

elastic = NomadConfig(
    host='localhost',
    port=9200,
    timeout=60,
    bulk_timeout=600,
    bulk_size=1000,
    entries_per_material_cap=1000,
    entries_index='nomad_entries_v1',
    materials_index='nomad_materials_v1',
)

keycloak = NomadConfig(
    server_url='https://nomad-lab.eu/fairdi/keycloak/auth/',
    public_server_url=None,
    realm_name='fairdi_nomad_prod',
    username='admin',
    password='password',
    client_id='nomad_public',
    client_secret=None)

mongo = NomadConfig(
    host='localhost',
    port=27017,
    db_name='nomad_v1'
)

logstash = NomadConfig(
    enabled=False,
    host='localhost',
    tcp_port='5000',
    level=logging.DEBUG
)

services = NomadConfig(
    api_host='localhost',
    api_port=8000,
    api_base_path='/fairdi/nomad/latest',
    api_secret='defaultApiSecret',
    api_chaos=0,
    admin_user_id='00000000-0000-0000-0000-000000000000',
    not_processed_value='not processed',
    unavailable_value='unavailable',
    https=False,
    https_upload=False,
    upload_limit=10,
    force_raw_file_decoding=False,
    download_scan_size=500,
    download_scan_timeout=u'30m'
)

oasis = NomadConfig(
    central_nomad_deployment_url='https://nomad-lab.eu/prod/v1/api',
    allowed_users=None,  # a list of usernames or user account emails
    uses_central_user_management=False,
    is_oasis=False
)

tests = NomadConfig(
    default_timeout=60
)


def api_url(ssl: bool = True, api: str = 'api', api_host: str = None, api_port: int = None):
    '''
    Returns the url of the current running nomad API. This is for server-side use.
    This is not the NOMAD url to use as a client, use `nomad.config.client.url` instead.
    '''
    if api_port is None:
        api_port = services.api_port
    if api_host is None:
        api_host = services.api_host
    protocol = 'https' if services.https and ssl else 'http'
    host_and_port = api_host
    if api_port not in [80, 443]:
        host_and_port += ':' + str(api_port)
    base_path = services.api_base_path.strip('/')
    return f'{protocol}://{host_and_port}/{base_path}/{api}'


def gui_url(page: str = None):
    base = api_url(True)[:-3]
    if base.endswith('/'):
        base = base[:-1]

    if page is not None:
        return '%s/gui/%s' % (base, page)

    return '%s/gui' % base


def _check_config():
    """Used to check that the current configuration is valid. Should only be
    called once after the final config is loaded.

    Raises:
        AssertionError: if there is a contradiction or invalid values in the
            config file settings.
    """
    # The AFLOW symmetry information is checked once on import
    proto_symmetry_tolerance = normalize.prototype_symmetry_tolerance
    symmetry_tolerance = normalize.symmetry_tolerance
    if proto_symmetry_tolerance != symmetry_tolerance:
        raise AssertionError(
            "The AFLOW prototype information is outdated due to changed tolerance "
            "for symmetry detection. Please update the AFLOW prototype information "
            "by running the CLI command 'nomad admin ops prototype-update "
            "--matches-only'."
        )

    if normalize.springer_db_path and not os.path.exists(normalize.springer_db_path):
        normalize.springer_db_path = None

    if keycloak.public_server_url is None:
        keycloak.public_server_url = keycloak.server_url

    def set_external_path(source_obj, source_key, target_obj, target_key, overwrite=False):
        source_value = getattr(source_obj, source_key)
        target_value = getattr(target_obj, target_key)

        if target_value and not overwrite:
            return

        if not source_value:
            return

        if fs.external_working_directory and not os.path.isabs(source_value):
            target_value = os.path.join(fs.external_working_directory, source_value)
        else:
            target_value = source_value

        setattr(target_obj, target_key, target_value)

    set_external_path(fs, 'staging', fs, 'staging_external')
    set_external_path(fs, 'public', fs, 'public_external')
    set_external_path(north, 'users_fs', north, 'users_fs', overwrite=True)
    set_external_path(north, 'shared_fs', north, 'shared_fs', overwrite=True)


mail = NomadConfig(
    enabled=False,
    with_login=False,
    host='',
    port=8995,
    user='',
    password='',
    from_address='support@nomad-lab.eu',
    cc_address='support@nomad-lab.eu'
)

normalize = NomadConfig(
    # The system size limit for running the dimensionality analysis. For very
    # large systems the dimensionality analysis will get too expensive.
    system_classification_with_clusters_threshold=64,
    # Symmetry tolerance controls the precision used by spglib in order to find
    # symmetries. The atoms are allowed to move 1/2*symmetry_tolerance from
    # their symmetry positions in order for spglib to still detect symmetries.
    # The unit is angstroms. The value of 0.1 is used e.g. by Materials Project
    # according to
    # https://pymatgen.org/pymatgen.symmetry.analyzer.html#pymatgen.symmetry.analyzer.SpacegroupAnalyzer
    symmetry_tolerance=0.1,
    # The symmetry tolerance used in aflow prototype matching. Should only be
    # changed before re-running the prototype detection.
    prototype_symmetry_tolerance=0.1,
    # Maximum number of atoms in the single cell of a 2D material for it to be
    # considered valid.
    max_2d_single_cell_size=7,
    # The distance tolerance between atoms for grouping them into the same
    # cluster. Used in detecting system type.
    cluster_threshold=2.5,
    # Defines the "bin size" for rounding cell angles for the material hash
    angle_rounding=float(10.0),  # unit: degree
    # The threshold for a system to be considered "flat". Used e.g. when
    # determining if a 2D structure is purely 2-dimensional to allow extra rigid
    # transformations that are improper in 3D but proper in 2D.
    flat_dim_threshold=0.1,
    # The threshold for point equality in k-space. Unit: 1/m.
    k_space_precision=150e6,
    # The energy threshold for how much a band can be on top or below the fermi
    # level in order to still detect a gap. Unit: Joule.
    band_structure_energy_tolerance=8.01088e-21,  # 0.05 eV
    springer_db_path=os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'normalizing/data/springer.msg'
    )
)

resources = NomadConfig(
    enabled=False,
    db_name='nomad_v1_resources',
    # Maxmimum time a resource is stored in mongodb before being updated.
    max_time_in_mongo=60 * 60 * 24 * 365.,
    # Number of download retries
    download_retries=2,
    # Delay in seconds before each successive retry
    download_retry_delay=10,
    # Maximum number of httpx connections
    max_connections=10
)

paths = NomadConfig(
    similarity="",
)

client = NomadConfig(
    user=None,
    password=None,
    access_token=None,
    url='http://nomad-lab.eu/prod/v1/api'
)

datacite = NomadConfig(
    mds_host='https://mds.datacite.org',
    enabled=False,
    prefix='10.17172',
    user='*',
    password='*'
)

meta = NomadConfig(
    version=__version__,
    commit='',
    deployment='devel',  # A human-friendly name of the nomad deployment
    deployment_url='https://my-oasis.org/api',  # The deployment's url (api url).
    label=None,
    default_domain='dft',
    service='unknown nomad service',
    name='novel materials discovery (NOMAD)',
    description='A FAIR data sharing platform for materials science data',
    homepage='https://nomad-lab.eu',
    source_url='https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR',
    maintainer_email='markus.scheidgen@physik.hu-berlin.de',
    beta=None
)

gitlab = NomadConfig(
    private_token='not set'
)

reprocess = NomadConfig(
    # Configures standard behaviour when reprocessing.
    # Note, the settings only matter for published uploads and entries. For uploads in
    # staging, we always reparse, add newfound entries, and delete unmatched entries.
    rematch_published=True,
    reprocess_existing_entries=True,
    use_original_parser=False,
    add_matched_entries_to_published=True,
    delete_unmatched_published_entries=False,
    index_invidiual_entries=False
)

process = NomadConfig(
    # Configures if to store the corresponding package definition in mongodb.
    store_package_definition_in_mongo=False,
    # Configures if to attach definition id to `m_def`, note it is different from `m_def_id`.
    # The `m_def_id` will be exported with the `with_def_id=True` via `m_to_dict`.
    add_definition_id_to_reference=False,
    # write `m_def_id` to the archive
    write_definition_id_to_archive=False,
    index_materials=True,
    reuse_parser=True,
    metadata_file_name='nomad',
    metadata_file_extensions=('json', 'yaml', 'yml')
)

rfc3161_timestamp = NomadConfig(
    # rfc3161ng timestamping server
    server='http://time.certum.pl/',
    # cert PATH used for rfc3161ng timestamping server
    cert=None,
    # hash algorithm for rfc3161ng timestamping server, depends on the server
    hash_algorithm='sha256',
    username=None,
    password=None
)

bundle_export = NomadConfig(
    # General settings
    default_cli_bundle_export_path='./bundles',

    # Default settings
    default_settings=NomadConfig(
        # General default settings.
        include_raw_files=True,
        include_archive_files=True,
        include_datasets=True,
    ),

    default_settings_cli=NomadConfig(
        # Additional default settings, applied when exporting using the CLI (command-line interface).
        # This allows to override some of the settings specified in the general default settings above.
    )
)

bundle_import = NomadConfig(
    # General settings
    required_nomad_version='1.1.2',  # Minimum  nomad version of bundles required for import
    default_cli_bundle_import_path='./bundles',

    # Permission settings
    allow_bundles_from_oasis=False,  # If oasis admins can "push" bundles to this NOMAD deployment
    allow_unpublished_bundles_from_oasis=False,  # If oasis admins can "push" bundles of unpublished uploads

    # Default settings
    default_settings=NomadConfig(
        # General default settings.
        include_raw_files=True,
        include_archive_files=True,
        include_datasets=True,
        include_bundle_info=True,  # Keeps the bundle_info.json file (not necessary but nice to have)
        keep_original_timestamps=False,  # If all time stamps (create time, publish time etc) should be imported from the bundle
        set_from_oasis=True,  # If the from_oasis flag and oasis_deployment_url should be set
        # Cleanup settings
        delete_upload_on_fail=False,  # If False, the entries are just removed from the ES index on failure
        delete_bundle_on_fail=True,  # Deletes the source bundle if the import fails
        delete_bundle_on_success=True,  # Deletes the source bundle if the import succeeds
        delete_bundle_include_parent_folder=True,  # When deleting the bundle, also include parent folder, if empty.

        # It is possible to trigger processing of the raw files, but it is no longer the
        # preferred way to import bundles. If used, the settings below control the reprocessing
        # behaviour (see the config for `reprocess` for more info).
        trigger_processing=False,  # Set if you want to reprocess after import (not recommended).
        rematch_published=True,
        reprocess_existing_entries=True,
        use_original_parser=False,
        add_matched_entries_to_published=True,
        delete_unmatched_published_entries=False
    ),

    default_settings_cli=NomadConfig(
        # Additional default settings, applied when importing using the CLI (command-line interface).
        # This allows to override some of the settings specified in the general default settings above.
        delete_bundle_on_fail=False,
        delete_bundle_on_success=False
    )
)

north = NomadConfig(
    hub_connect_ip=None,  # Set this to host.docker.internal on windows/macos.
    hub_connect_url=None,
    hub_ip='0.0.0.0',
    docker_network=None,
    hub_host='localhost',
    hub_port=9000,
    shared_fs='.volumes/fs/north/shared',
    users_fs='.volumes/fs/north/users',
    jupyterhub_crypt_key=None,
    nomad_host=None,  # host name to reach nomad app from spawned containers
    windows=True,  # enable windows (as in windows the OS) hacks
)

archive = NomadConfig(
    block_size=256 * 1024,
    read_buffer_size=256 * 1024,  # GPFS needs at least 256K to achieve decent performance
    max_process_number=20,  # maximum number of processes can be assigned to process archive query
    min_entries_per_process=20  # minimum number of entries per process
)

ui = NomadConfig(
    default_unit_system='Custom',
    entry_context={
        'overview': {
            'include': [
                'sections',
                'definitions',
                'nexus',
                'material',
                'electronic',
                'optoelectronic',
                'vibrational',
                'mechanical',
                'thermodynamic',
                'structural',
                'dynamical',
                'geometry_optimization',
                'spectroscopy',
                'references'
            ],
            'exclude': [
                'relatedResources'
            ],
            'options': {
                'sections': {'error': 'Could not render section card.'},
                'definitions': {'error': 'Could not render definitions card.'},
                'nexus': {'error': 'Could not render NeXus card.'},
                'material': {'error': 'Could not render material card.'},
                'electronic': {'error': 'Could not render electronic properties.'},
                'optoelectronic': {'error': 'Could not render optoelectronic properties.'},
                'vibrational': {'error': 'Could not render vibrational properties.'},
                'mechanical': {'error': 'Could not render mechanical properties.'},
                'thermodynamic': {'error': 'Could not render thermodynamic properties.'},
                'structural': {'error': 'Could not render structural properties.'},
                'geometry_optimization': {'error': 'Could not render geometry optimization.'},
                'spectroscopy': {'error': 'Could not render spectroscopic properties.'},
                'references': {'error': 'Could not render references card.'},
                'relatedResources': {'error': 'Could not render related resources card.'},
            }
        }
    },
    search_contexts={
        "include": ["entries", "eln", "materials", "solar_cells"],
        "exclude": [],
        "options": {
            "entries": {
                'label': "Entries",
                'path': "entries",
                'resource': 'entries',
                'breadcrumb': "Entries search",
                'description': "Search individual entries",
                'help': {
                    'title': 'Entries search',
                    'content': inspect.cleandoc(r'''
                        This page allows you to **search entries** within NOMAD. Entries represent
                        individual calculations or experiments that have bee uploaded into NOMAD.

                        The search page consists of three main elements: the filter panel, the search
                        bar, and the result list.

                        The filter panel on the left allows you to graphically explore and enter
                        different search filters. It also gives a visual indication of the currently
                        active search filters for each category. This is a good place to start exploring
                        the available search filters and their meaning.

                        The search bar allows you to specify filters by typing them in and pressing
                        enter. You can also start by simply typing keywords of interest, which will
                        toggle a list of suggestions. For numerical data you can also use range queries,
                        e.g. \`0.0 < band_gap <= 0.1\`.

                        Notice that the units used in the filter panel and in the queries can be changed
                        using the **units** button on the top right corner. When using the search bar,
                        you can also specify a unit by typing the unit abbreviations, e.g. \`band_gap >=
                        0.1 Ha\`

                        The result list on the right is automatically updated according to the filters
                        you have specified. You can browse through the results by scrolling through the
                        available items and loading more results as you go. Here you can also change the
                        sorting of the results, modify the displayed columns, access individual entries
                        or even download the raw data or the archive document by selecting individual
                        entries and pressing the download button that appears. The ellipsis button shown
                        for each entry will navigate you to that entry's page. This entry page will show
                        more metadata, raw files, the entry's archive, and processing logs.
                    '''),
                },
                'pagination': {
                    'order_by': 'upload_create_time',
                    'order': 'desc',
                    'page_size': 20,
                },
                'columns': {
                    'enable': [
                        'entry_name',
                        'results.material.chemical_formula_hill',
                        'entry_type',
                        'upload_create_time',
                        'authors'
                    ],
                    'include': [
                        'entry_name',
                        'results.material.chemical_formula_hill',
                        'entry_type',
                        'results.method.method_name',
                        'results.method.simulation.program_name',
                        'results.method.simulation.dft.basis_set_name',
                        'results.method.simulation.dft.xc_functional_type',
                        'results.material.structural_type',
                        'results.material.symmetry.crystal_system',
                        'results.material.symmetry.space_group_symbol',
                        'results.material.symmetry.space_group_number',
                        'results.eln.lab_ids',
                        'results.eln.sections',
                        'results.eln.methods',
                        'results.eln.tags',
                        'results.eln.instruments',
                        'mainfile',
                        'upload_create_time',
                        'authors',
                        'comment',
                        'references',
                        'datasets',
                        'published',
                    ],
                    'exclude': [],
                    'options': {
                        'entry_name': {'label': 'Name', 'align': 'left'},
                        'results.material.chemical_formula_hill': {'label': 'Formula', 'align': 'left'},
                        'entry_type': {'label': 'Entry type', 'align': 'left'},
                        'results.method.method_name': {'label': 'Method name'},
                        'results.method.simulation.program_name': {'label': 'Program name'},
                        'results.method.simulation.dft.basis_set_name': {'label': 'Basis set name'},
                        'results.method.simulation.dft.xc_functional_type': {'label': 'XC functional type'},
                        'results.material.structural_type': {'label': 'Structural type'},
                        'results.material.symmetry.crystal_system': {'label': 'Crystal system'},
                        'results.material.symmetry.space_group_symbol': {'label': 'Space group symbol'},
                        'results.material.symmetry.space_group_number': {'label': 'Space group number'},
                        'results.eln.lab_ids': {'label': 'Lab IDs'},
                        'results.eln.sections': {'label': 'Sections'},
                        'results.eln.methods': {'label': 'Methods'},
                        'results.eln.tags': {'label': 'Tags'},
                        'results.eln.instruments': {'label': 'Instruments'},
                        'mainfile': {'label': 'Mainfile', 'align': 'left'},
                        'upload_create_time': {'label': 'Upload time', 'align': 'left'},
                        'authors': {'label': 'Authors', 'align': 'left'},
                        'comment': {'label': 'Comment', 'align': 'left'},
                        'references': {'label': 'References', 'align': 'left'},
                        'datasets': {'label': 'Datasets', 'align': 'left'},
                        'published': {'label': 'Access'}
                    }
                },
                'rows': {
                    'actions': {
                        'enable': True
                    },
                    'details': {
                        'enable': True
                    },
                    'selection': {
                        'enable': True
                    }
                },
                'filter_menus': {
                    'include': [
                        'material',
                        'elements',
                        'symmetry',
                        'method',
                        'simulation',
                        'dft',
                        'gw',
                        'experiment',
                        'eels',
                        'properties',
                        'electronic',
                        'optoelectronic',
                        'vibrational',
                        'mechanical',
                        'spectroscopy',
                        'thermodynamic',
                        'geometry_optimization',
                        'eln',
                        'author',
                        'dataset',
                        'access',
                        'ids',
                        'processed_data_quantities',
                        'optimade',
                    ],
                    'exclude': [],
                    'options': {
                        'material': {'label': 'Material', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'elements': {'label': 'Elements / Formula', 'level': 1, 'size': 'large', 'menu_items': {}},
                        'symmetry': {'label': 'Symmetry', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'method': {'label': 'Method', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'simulation': {'label': 'Simulation', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'dft': {'label': 'DFT', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'gw': {'label': 'GW', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'experiment': {'label': 'Experiment', 'level': 1, 'size': 'small'},
                        'eels': {'label': 'EELS', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'properties': {'label': 'Properties', 'level': 0, 'size': 'small'},
                        'electronic': {'label': 'Electronic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'optoelectronic': {'label': 'Optoelectronic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'vibrational': {'label': 'Vibrational', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'mechanical': {'label': 'Mechanical', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'spectroscopy': {'label': 'Spectroscopy', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'thermodynamic': {'label': 'Thermodynamic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'geometry_optimization': {'label': 'Geometry Optimization', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'eln': {'label': 'Electronic Lab Notebook', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'author': {'label': 'Author / Origin', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'dataset': {'label': 'Dataset', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'access': {'label': 'Access', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'ids': {'label': 'IDs', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'processed_data_quantities': {'label': 'Processed Data Quantities', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'optimade': {'label': 'Optimade', 'level': 0, 'size': 'medium', 'menu_items': {}},
                    }
                }
            },
            "eln": {
                'label': "ELN",
                'path': "eln",
                'resource': 'entries',
                'breadcrumb': "ELN entries search",
                'description': "Search individual ELN entries",
                'help': {
                    'title': 'ELN entries search',
                    'content': inspect.cleandoc(r'''
                        This page allows you to specifically **search ELN entries** within NOMAD.
                        It is very similar to the *Entries search*, but with a reduced
                        filter set and specialized arrangement of default columns.
                    '''),
                },
                'pagination': {
                    'order_by': 'upload_create_time',
                    'order': 'desc',
                    'page_size': 20,
                },
                'columns': {
                    'enable': [
                        'entry_name',
                        'entry_type',
                        'upload_create_time',
                        'authors'
                    ],
                    'include': [
                        'entry_name',
                        'results.material.chemical_formula_hill',
                        'entry_type',
                        'results.method.method_name',
                        'results.method.simulation.program_name',
                        'results.method.simulation.dft.basis_set_name',
                        'results.method.simulation.dft.xc_functional_type',
                        'results.material.structural_type',
                        'results.material.symmetry.crystal_system',
                        'results.material.symmetry.space_group_symbol',
                        'results.material.symmetry.space_group_number',
                        'results.eln.lab_ids',
                        'results.eln.sections',
                        'results.eln.methods',
                        'results.eln.tags',
                        'results.eln.instruments',
                        'mainfile',
                        'upload_create_time',
                        'authors',
                        'comment',
                        'references',
                        'datasets',
                        'published',
                    ],
                    'exclude': [],
                    'options': {
                        'entry_name': {'label': 'Name', 'align': 'left'},
                        'results.material.chemical_formula_hill': {'label': 'Formula', 'align': 'left'},
                        'entry_type': {'label': 'Entry type', 'align': 'left'},
                        'results.method.method_name': {'label': 'Method name'},
                        'results.method.simulation.program_name': {'label': 'Program name'},
                        'results.method.simulation.dft.basis_set_name': {'label': 'Basis set name'},
                        'results.method.simulation.dft.xc_functional_type': {'label': 'XC functional type'},
                        'results.material.structural_type': {'label': 'Structural type'},
                        'results.material.symmetry.crystal_system': {'label': 'Crystal system'},
                        'results.material.symmetry.space_group_symbol': {'label': 'Space group symbol'},
                        'results.material.symmetry.space_group_number': {'label': 'Space group number'},
                        'results.eln.lab_ids': {'label': 'Lab IDs'},
                        'results.eln.sections': {'label': 'Sections'},
                        'results.eln.methods': {'label': 'Methods'},
                        'results.eln.tags': {'label': 'Tags'},
                        'results.eln.instruments': {'label': 'Instruments'},
                        'mainfile': {'label': 'Mainfile', 'align': 'left'},
                        'upload_create_time': {'label': 'Upload time', 'align': 'left'},
                        'authors': {'label': 'Authors', 'align': 'left'},
                        'comment': {'label': 'Comment', 'align': 'left'},
                        'references': {'label': 'References', 'align': 'left'},
                        'datasets': {'label': 'Datasets', 'align': 'left'},
                        'published': {'label': 'Access'}
                    }
                },
                'rows': {
                    'actions': {
                        'enable': True
                    },
                    'details': {
                        'enable': True
                    },
                    'selection': {
                        'enable': True
                    }
                },
                'filter_menus': {
                    'include': [
                        'material',
                        'elements',
                        'eln',
                        'custom_quantities',
                        'author',
                        'dataset',
                        'access',
                        'ids',
                        'processed_data_quantities',
                        'optimade',
                    ],
                    'exclude': [],
                    'options': {
                        'material': {'label': 'Material', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'elements': {'label': 'Elements / Formula', 'level': 1, 'size': 'large', 'menu_items': {}},
                        'eln': {'label': 'Electronic Lab Notebook', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'custom_quantities': {'label': 'Custom quantities', 'level': 0, 'size': 'large', 'menu_items': {}},
                        'author': {'label': 'Author / Origin', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'dataset': {'label': 'Dataset', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'access': {'label': 'Access', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'ids': {'label': 'IDs', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'processed_data_quantities': {'label': 'Processed Data Quantities', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'optimade': {'label': 'Optimade', 'level': 0, 'size': 'medium', 'menu_items': {}},
                    }
                }
            },
            "materials": {
                'label': "Materials",
                'path': "materials",
                'resource': 'materials',
                'breadcrumb': "Materials search",
                'description': "Search materials that are identified from the entries",
                'help': {
                    'title': 'Materials search',
                    'content': inspect.cleandoc(r'''
                        This page allows you to **search materials** within NOMAD. NOMAD can
                        automatically detect the material from individual entries and can then group the
                        data by using these detected materials. This allows you to search individual
                        materials which have properties that are aggregated from several entries.

                        The search page consists of three main elements: the filter panel, the search
                        bar, and the result list.

                        The filter panel on the left allows you to graphically explore and enter
                        different search filters. It also gives a visual indication of the currently
                        active search filters for each category. This is a good place to start exploring
                        the available search filters and their meaning.

                        The search bar allows you to specify filters by typing them in and pressing
                        enter. You can also start by simply typing keywords of interest, which will
                        toggle a list of suggestions. For numerical data you can also use range queries,
                        e.g. \`0.0 < band_gap <= 0.1\`.

                        The units used in the filter panel and in the queries can be changed
                        using the **units** button on the top right corner. When using the search bar,
                        you can also specify a unit by typing the unit abbreviations, e.g. \`band_gap >=
                        0.1 Ha\`.

                        Notice that by default the properties that you search can be combined from
                        several different entries. If instead you wish to search for a material with an
                        individual entry fullfilling your search criteria, uncheck the **combine results
                        from several entries**-checkbox.

                        The result list on the right is automatically updated according to the filters
                        you have specified. You can scroll through the available items and load more
                        results as you go. Here you can also change the sorting of the results, modify
                        the displayed columns and access individual materials. The ellipsis button shown
                        for each material will navigate you into the material overview page within the
                        NOMAD Encyclopedia. This page will show a more detailed overview for that
                        specific material.
                    '''),
                },
                'pagination': {
                    'order_by': 'chemical_formula_hill',
                    'order': 'asc'
                },
                'columns': {
                    'enable': [
                        'chemical_formula_hill',
                        'structural_type',
                        'symmetry.structure_name',
                        'symmetry.space_group_number',
                        'symmetry.crystal_system',
                    ],
                    'include': [
                        'chemical_formula_hill',
                        'structural_type',
                        'symmetry.structure_name',
                        'symmetry.crystal_system',
                        'symmetry.space_group_symbol',
                        'symmetry.space_group_number',
                        'material_id',
                    ],
                    'exclude': [],
                    'options': {
                        'chemical_formula_hill': {'label': 'Formula', 'align': 'left'},
                        'structural_type': {'label': 'Structural type'},
                        'symmetry.structure_name': {'label': 'Structure name'},
                        'symmetry.crystal_system': {'label': 'Crystal system'},
                        'symmetry.space_group_symbol': {'label': 'Space group symbol'},
                        'symmetry.space_group_number': {'label': 'Space group number'},
                        'material_id': {'label': 'Material ID'},
                    }
                },
                'rows': {
                    'actions': {
                        'enable': True
                    },
                    'details': {
                        'enable': False
                    },
                    'selection': {
                        'enable': False
                    }
                },
                'filter_menus': {
                    'include': [
                        'material',
                        'elements',
                        'symmetry',
                        'method',
                        'simulation',
                        'dft',
                        'gw',
                        'experiment',
                        'eels',
                        'properties',
                        'electronic',
                        'optoelectronic',
                        'vibrational',
                        'mechanical',
                        'spectroscopy',
                        'thermodynamic',
                        'geometry_optimization',
                        'eln',
                        'author',
                        'dataset',
                        'access',
                        'ids',
                        'processed_data_quantities',
                        'optimade',
                        'combine',
                    ],
                    'exclude': [],
                    'options': {
                        'material': {'label': 'Material', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'elements': {'label': 'Elements / Formula', 'level': 1, 'size': 'large', 'menu_items': {}},
                        'symmetry': {'label': 'Symmetry', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'method': {'label': 'Method', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'simulation': {'label': 'Simulation', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'dft': {'label': 'DFT', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'gw': {'label': 'GW', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'experiment': {'label': 'Experiment', 'level': 1, 'size': 'small'},
                        'eels': {'label': 'EELS', 'level': 2, 'size': 'small', 'menu_items': {}},
                        'properties': {'label': 'Properties', 'level': 0, 'size': 'small'},
                        'electronic': {'label': 'Electronic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'optoelectronic': {'label': 'Optoelectronic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'vibrational': {'label': 'Vibrational', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'mechanical': {'label': 'Mechanical', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'spectroscopy': {'label': 'Spectroscopy', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'thermodynamic': {'label': 'Thermodynamic', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'geometry_optimization': {'label': 'Geometry Optimization', 'level': 1, 'size': 'small', 'menu_items': {}},
                        'eln': {'label': 'Electronic Lab Notebook', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'author': {'label': 'Author / Origin', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'dataset': {'label': 'Dataset', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'access': {'label': 'Access', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'ids': {'label': 'IDs', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'processed_data_quantities': {'label': 'Processed Data Quantities', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'optimade': {'label': 'Optimade', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'combine': {
                            'actions': {
                                'include': ['combine'],
                                'options': {
                                    'combine': {
                                        'type': 'checkbox',
                                        'label': "Combine results from several entries",
                                        'quantity': 'combine'
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "solar_cells": {
                'label': "Solar Cells",
                'path': "solar-cells",
                'resource': 'entries',
                'breadcrumb': "Solar cells search",
                'description': "Search solar cells in NOMAD",
                'help': {
                    'title': 'Solar cells search',
                    'content': inspect.cleandoc(r'''
                        This page allows you to **search solar cells** within NOMAD.
                        You can search for solar cells by their properties, by the chemistry of the absorber layer,
                        preparation method, or their origin.

                        The search page consists of three main elements: the filter panel, the search
                        bar, and the result list.

                        The filter panel on the left allows you to graphically explore and enter
                        different search filters. It also gives a visual indication of the currently
                        active search filters for each category. This is a good place to start exploring
                        the available search filters and their meaning. But clikcing in the "+" button
                        you could add the filter widgets to the central part of the page and combine them.
                        Try adding the periodic table widget to the main pannel and select some elements
                        contained in the absorber layer.

                        The search bar allows you to specify filters by typing them in and pressing
                        enter. You can also start by simply typing keywords of interest, which will
                        toggle a list of suggestions. For numerical data you can also use range queries,
                        e.g. \`0.0 < efficiency <= 20.1\`.

                        The units used in the filter panel and in the queries can be changed
                        using the **units** button on the top right corner. When using the search bar,
                        you can also specify a unit by typing the unit abbreviations, e.g. \`band_gap >=
                        0.1 Ha\`.

                        The result list on the right is automatically updated according to the filters
                        you have specified. You can browse through the results by scrolling through the
                        available items and loading more results as you go. Here you can also change the
                        sorting of the results, modify the displayed columns, download the raw data
                        or the archive document by selecting individual entries and pressing the download
                        cloud button that appears.

                        The ellipsis button (three dots) shown for each entry will navigate
                        you to that entry's page. This entry page will show more metadata,
                        raw files, the entry's archive, and processing logs.
                    '''),
                },
                'pagination': {
                    'order_by': 'results.properties.optoelectronic.solar_cell.efficiency',
                    'order': 'desc',
                    'page_size': 20,
                },
                'filters_locked': {
                    'results.material.functional_type': 'solar cell'
                },
                'columns': {
                    'enable': [
                        'results.material.chemical_formula_descriptive',
                        'results.properties.optoelectronic.solar_cell.efficiency',
                        'results.properties.optoelectronic.solar_cell.open_circuit_voltage',
                        'results.properties.optoelectronic.solar_cell.short_circuit_current_density',
                        'results.properties.optoelectronic.solar_cell.fill_factor',
                        'references'
                    ],
                    'include': [
                        'entry_name',
                        'results.material.chemical_formula_hill',
                        'results.material.chemical_formula_descriptive',
                        'results.properties.optoelectronic.solar_cell.efficiency',
                        'results.properties.optoelectronic.solar_cell.open_circuit_voltage',
                        'results.properties.optoelectronic.solar_cell.short_circuit_current_density',
                        'results.properties.optoelectronic.solar_cell.fill_factor',
                        # 'results.properties.optoelectronic.band_gap[0].value',
                        'results.properties.optoelectronic.solar_cell.device_stack',
                        'results.properties.optoelectronic.solar_cell.device_architecture',
                        'results.properties.optoelectronic.solar_cell.illumination_intensity',
                        'results.properties.optoelectronic.solar_cell.absorber_fabrication',
                        'entry_type',
                        'results.material.structural_type',
                        'results.eln.lab_ids',
                        'results.eln.sections',
                        'results.eln.methods',
                        'results.eln.tags',
                        'results.eln.instruments',
                        'mainfile',
                        'upload_create_time',
                        'authors',
                        'comment',
                        'references',
                        'datasets',
                        'published',
                    ],
                    'exclude': [],
                    'options': {
                        'entry_name': {'label': 'Name', 'align': 'left'},
                        'results.material.chemical_formula_hill': {'label': 'Formula', 'align': 'left'},
                        'results.material.chemical_formula_descriptive': {'label': 'Descriptive Formula', 'align': 'left'},
                        'entry_type': {'label': 'Entry type', 'align': 'left'},
                        'results.material.structural_type': {'label': 'Structural type'},
                        'results.properties.optoelectronic.solar_cell.efficiency': {
                            'label': 'Efficiency (%)',
                            'format': {
                                'decimals': 2,
                                'mode': 'standard',
                            },
                        },
                        'results.properties.optoelectronic.solar_cell.open_circuit_voltage': {
                            'label': 'Open circuit voltage',
                            'unit': 'V',
                            'format': {
                                'decimals': 3,
                                'mode': 'standard',
                            },
                        },
                        'results.properties.optoelectronic.solar_cell.short_circuit_current_density': {
                            'label': 'Short circuit current density',
                            'unit': 'A/m**2',
                            'format': {
                                'decimals': 3,
                                'mode': 'standard',
                            },
                        },
                        'results.properties.optoelectronic.solar_cell.fill_factor': {
                            'label': 'Fill factor',
                            'format': {
                                'decimals': 3,
                                'mode': 'standard',
                            },
                        },
                        'results.properties.optoelectronic.solar_cell.illumination_intensity': {
                            'label': 'Illum. intensity',
                            'unit': 'W/m**2',
                            'format': {
                                'decimals': 3,
                                'mode': 'standard',
                            },
                        },
                        # 'results.properties.optoelectronic.band_gap[0].value': {'label': 'Bandgap (eV)'},
                        'results.eln.lab_ids': {'label': 'Lab IDs'},
                        'results.eln.sections': {'label': 'Sections'},
                        'results.eln.methods': {'label': 'Methods'},
                        'results.eln.tags': {'label': 'Tags'},
                        'results.eln.instruments': {'label': 'Instruments'},
                        'mainfile': {'label': 'Mainfile', 'align': 'left'},
                        'upload_create_time': {'label': 'Upload time', 'align': 'left'},
                        'authors': {'label': 'Authors', 'align': 'left'},
                        'comment': {'label': 'Comment', 'align': 'left'},
                        'references': {'label': 'References', 'align': 'left'},
                        'datasets': {'label': 'Datasets', 'align': 'left'},
                        'published': {'label': 'Access'},
                    },
                },
                'rows': {
                    'actions': {
                        'enable': True
                    },
                    'details': {
                        'enable': True
                    },
                    'selection': {
                        'enable': True
                    }
                },
                'filter_menus': {
                    'include': [
                        'material',
                        'elements',
                        'properties',
                        'optoelectronic',
                        'eln',
                        'author',
                        'dataset',
                        'access',
                        'ids',
                        'processed_data_quantities',
                        'optimade',
                    ],
                    'exclude': [],
                    'options': {
                        'material': {'label': 'Material', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'elements': {'label': 'Elements / Formula', 'level': 0, 'size': 'large', 'menu_items': {}},
                        'properties': {'label': 'Properties', 'level': 0, 'size': 'small'},
                        'optoelectronic': {'label': 'Solar Cell Properties', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'eln': {'label': 'Electronic Lab Notebook', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'author': {'label': 'Author / Origin', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'dataset': {'label': 'Dataset', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'access': {'label': 'Access', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'ids': {'label': 'IDs', 'level': 0, 'size': 'small', 'menu_items': {}},
                        'processed_data_quantities': {'label': 'Processed Data Quantities', 'level': 0, 'size': 'medium', 'menu_items': {}},
                        'optimade': {'label': 'Optimade', 'level': 0, 'size': 'medium', 'menu_items': {}},
                    }
                }
            }
        }
    }
)


def north_url(ssl: bool = True):
    return api_url(ssl=ssl, api='north', api_host=north.hub_host, api_port=north.hub_port)


auxfile_cutoff = 100
parser_matching_size = 150 * 80  # 150 lines of 80 ASCII characters per line
console_log_level = logging.WARNING
max_upload_size = 32 * (1024 ** 3)
raw_file_strip_cutoff = 1000
max_entry_download = 500000
encyclopedia_base = "https://nomad-lab.eu/prod/rae/encyclopedia/#"
aitoolkit_enabled = False
use_empty_parsers = False


def normalize_loglevel(value, default_level=logging.INFO):
    plain_value = value
    if plain_value is None:
        return default_level
    else:
        try:
            return int(plain_value)
        except ValueError:
            return getattr(logging, plain_value)


_transformations = {
    'console_log_level': normalize_loglevel,
    'logstash_level': normalize_loglevel
}


# use std python logger, since logging is not configured while loading configuration
logger = logging.getLogger(__name__)


def _merge(a: dict, b: dict, path: List[str] = None) -> dict:
    '''
    Recursively merges b into a. Will add new key-value pairs, and will
    overwrite existing key-value pairs. Notice that this mutates the original
    dictionary a and if you want to return a copy, you will want to first
    (deep)copy the original dictionary.
    '''
    if path is None: path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                _merge(a[key], b[key], path + [str(key)])
            else:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a


def _apply(key, value, raise_error: bool = True) -> None:
    '''
    Changes the config according to given key and value. The first part of a key
    (with ``_`` as a separator) is interpreted as a group of settings. E.g. ``fs_staging``
    leading to ``config.fs.staging``.
    '''
    full_key = key
    try:
        group_key, config_key = full_key.split('_', 1)
    except Exception:
        if raise_error:
            logger.error(f'config key does not exist: {full_key}')
        return

    current = globals()

    if group_key not in current:
        if key not in current:
            if raise_error:
                logger.error(f'config key does not exist: {full_key}')
            return
    else:
        current = current[group_key]
        if not isinstance(current, NomadConfig):
            if raise_error:
                logger.error(f'config key does not exist: {full_key}')
            return

        if config_key not in current:
            if raise_error:
                logger.error(f'config key does not exist: {full_key}')
            return

        key = config_key

    try:
        current_value = current[key]
        if current_value is not None and not isinstance(value, type(current_value)):
            value = _transformations.get(full_key, type(current_value))(value)

        if isinstance(value, dict):
            value = _merge(current[key], value)

        current[key] = value
        logger.info(f'set config setting {full_key}={value}')
    except Exception as e:
        logger.error(f'cannot set config setting {full_key}={value}: {e}')


def _apply_env_variables():
    kwargs = {
        key[len('NOMAD_'):].lower(): value
        for key, value in os.environ.items()
        if key.startswith('NOMAD_') and key != 'NOMAD_CONFIG'}

    for key, value in kwargs.items():
        _apply(key, value, raise_error=False)


def _apply_nomad_yaml():
    config_file = os.environ.get('NOMAD_CONFIG', 'nomad.yaml')

    if not os.path.exists(config_file):
        return

    with open(config_file, 'r') as stream:
        try:
            config_data = yaml.load(stream, Loader=getattr(yaml, 'FullLoader'))
        except yaml.YAMLError as e:
            logger.error(f'cannot read nomad config: {e}')
            return

    if not config_data:
        return

    for key, value in config_data.items():
        if isinstance(value, dict):
            group_key = key
            for key, value in value.items():
                _apply(f'{group_key}_{key}', value)
        else:
            _apply(key, value)


def load_config():
    '''
    Loads the configuration from nomad.yaml and environment.
    '''
    _apply_nomad_yaml()
    _apply_env_variables()
    _check_config()


load_config()
