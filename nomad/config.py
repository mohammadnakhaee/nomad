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

import logging
import os
import os.path
import yaml
import warnings
from kombu import Queue

from nomad import utils

warnings.filterwarnings("ignore", message="numpy.dtype size changed")
warnings.filterwarnings("ignore", message="numpy.ufunc size changed")


class NomadConfig(utils.POPO):
    pass


# class ConfigProperty:
#     def __init__(
#             self, name: str, default_value: Union[int, str, bool], help: str = None,
#             env_var: str = None) -> None:
#         self.name = name
#         self.default_value = default_value,
#         self.help = help
#         self.env_var = env_var

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
    acks_late=True,
    routing=CELERY_QUEUE_ROUTING,
    task_queues=[
        Queue('calcs', routing_key='calcs', queue_arguments={'x-max-priority': 10}),
        Queue('uploads', routing_key='uploads', queue_arguments={'x-max-priority': 100})
    ]
)

fs = NomadConfig(
    tmp='.volumes/fs/tmp',
    staging='.volumes/fs/staging',
    public='.volumes/fs/public',
    migration_packages='.volumes/fs/migration_packages',
    prefix_size=2
)

elastic = NomadConfig(
    host='localhost',
    port=9200,
    index_name='nomad_fairdi_calcs'
)

repository_db = NomadConfig(
    sequential_publish=False,
    publish_enabled=True,
    host='localhost',
    port=5432,
    dbname='nomad_fairdi_repo_db',
    user='postgres',
    password='nomad'
)

mongo = NomadConfig(
    host='localhost',
    port=27017,
    db_name='nomad_fairdi'
)

logstash = NomadConfig(
    enabled=True,
    host='localhost',
    tcp_port='5000',
    level=logging.DEBUG
)

services = NomadConfig(
    api_host='localhost',
    api_port=8000,
    api_base_path='/nomad/api',
    api_secret='defaultApiSecret',
    admin_password='password',
    disable_reset=True
)


def upload_url():
    return 'http://%s:%s/%s/uploads' % (services.api_host, services.api_port, services.api_base_path[:-3])


migration_source_db = NomadConfig(
    host='db-repository.nomad.esc',
    port=5432,
    dbname='nomad_prod',
    user='nomadlab',
    password='*'
)

mail = NomadConfig(
    enabled=False,
    with_login=False,
    host='',
    port=8995,
    user='',
    password='',
    from_address='webmaster@nomad-coe.eu'
)

normalize = NomadConfig(
    all_systems=False
)

client = NomadConfig(
    user='leonard.hofstadter@nomad-fairdi.tests.de',
    password='password',
    url='http://localhost:8000/nomad/api'
)

console_log_level = logging.WARNING
service = 'unknown nomad service'
release = 'devel'
auxfile_cutoff = 30
version = '4.3'  # TODO replace with git hash?


def get_loglevel_from_env(key, default_level=logging.INFO):
    plain_value = os.environ.get(key, None)
    if plain_value is None:
        return default_level
    else:
        try:
            return int(plain_value)
        except ValueError:
            return getattr(logging, plain_value)


transformations = {
    'console_log_level': get_loglevel_from_env,
    'logstash_level': get_loglevel_from_env
}


# use std python logger, since logging is not configured while loading configuration
logger = logging.getLogger(__name__)


def apply(config, key, value) -> None:
    """
    Changes the config according to given key and value. The keys are interpreted as paths
    to config values with ``_`` as a separator. E.g. ``fs_staging`` leading to
    ``config.fs.staging``
    """

    path = list(reversed(key.split('_')))
    child_segment = None
    current_value = None
    child_config = config
    child_key = None

    try:
        while len(path) > 0:
            if child_segment is None:
                child_segment = path.pop()
            else:
                child_segment += '_' + path.pop()

            if child_segment in child_config:
                current_value = child_config[child_segment]

            if current_value is None:
                if len(path) == 0:
                    raise KeyError

                continue
            if isinstance(current_value, NomadConfig):
                child_config = current_value
                child_segment = None
            else:
                if len(path) > 0:
                    raise KeyError()

                child_key = child_segment
                break

        if child_key is None or current_value is None:
            raise KeyError()
    except KeyError:
        logger.error('config key %s does not exist' % key)

    if not isinstance(value, type(current_value)):
        try:
            value = transformations.get(key, type(current_value))(value)
        except Exception as e:
            logger.error(
                'config key %s value %s has wrong type: %s' % (key, str(value), str(e)))

    child_config[child_key] = value


def load_config(config_file: str = os.environ.get('NOMAD_CONFIG', 'nomad.yml')) -> None:
    # load yml and override defaults
    if os.path.exists(config_file):
        with open(config_file, 'r') as stream:
            try:
                config_data = yaml.load(stream)
            except yaml.YAMLError as e:
                logger.error('cannot read nomad config', exc_info=e)

        def adapt(config, new_config, child_key=None):
            for key, value in new_config.items():
                if key in config:
                    if child_key is None:
                        qualified_key = key
                    else:
                        qualified_key = '%s_%s' % (child_key, key)

                    current_value = config[key]
                    if isinstance(value, dict) and isinstance(current_value, NomadConfig):
                        adapt(current_value, value, qualified_key)
                    else:
                        if not isinstance(value, type(current_value)):
                            try:
                                value = transformations.get(qualified_key, type(current_value))(value)
                            except Exception as e:
                                logger.error(
                                    'config key %s value %s has wrong type: %s' % (key, str(value), str(e)))
                        else:
                            config[key] = value
                else:
                    logger.error('config key %s does not exist' % key)

        adapt(globals(), config_data)

    # load env and override yml and defaults
    kwargs = {
        key[len('NOMAD_'):].lower(): value
        for key, value in os.environ.items()
        if key.startswith('NOMAD_')
    }
    config = globals()
    for key, value in kwargs.items():
        apply(config, key, value)


load_config()
