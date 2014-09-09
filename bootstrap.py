#!/usr/bin/env python
from argparse import ArgumentParser
import glob2
import logging
import os
from subprocess import check_call, check_output
import shutil
import sys
import tempfile
import time

import glanceclient.v1
import keystoneclient.v2_0
import swiftclient
import yaml

SWIFT_CONTAINER_URL_FORMAT = '{}/{}'
SWIFT_CONTAINER_HEADERS = {
    'X-Container-Read': '.r:*'
}

log = logging.getLogger(__name__)

def configure_logger(verbose=False):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler)

    if verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.WARN)

def prepare_environment(config, image_metadata_url):
    environments = {
        'default': 'openstack',
        'environments': {
            'openstack': {
                'type': 'openstack',
                'use-floating-ip': True,
                'image-metadata-url': image_metadata_url,
                'network': config['network'],
                'auth-url': config['auth-url'],
                'region': config['region'],
                'tenant-name': config['tenant-name'],
                'auth-mode': 'userpass',
                'username': config['username'],
                'password': config['password'],
            }
        }
    }

    juju_path = os.path.expanduser('~/.juju')
    if not os.path.exists(juju_path):
        os.mkdir(juju_path)

    juju_env_path = os.path.join(juju_path, 'environments.yaml')

    log.debug('Creating Juju environment config')
    with open(juju_env_path, 'w') as fp:
        yaml.dump(environments, fp, default_flow_style=False)

def prepare_images(glance, series):
    images = {}

    for series_name, options in series.iteritems():
        images[series_name] = prepare_image(glance, options)

    for image in images.itervalues():
        if image.status != 'active':
            log.info('Waiting 10 seconds for image [%s]', image.name)
            time.sleep(10)

            image = glance.images.get(image.id)

    return images

def prepare_image(glance, options):
    for image in glance.images.list():
        if image.name == options['name']:
            log.debug('Image already exists [%s]', image.name)
            return image

    log.debug('Creating image [%s]', image.name)

    return glance.images.create(
        name=options['name'],
        disk_format=options.get('disk-format', 'qcow2'),
        container_format=options.get('container-format', 'bare'),
        copy_from=options['url'],
    )

def push_image_metadata(swift, container_name, images):
    log.debug('Preparing Swift container [%s]', container_name)
    swift.put_container(container_name)
    swift.post_container(container_name, headers=SWIFT_CONTAINER_HEADERS)

    cwd = os.getcwd()

    metadata_tmp = tempfile.mkdtemp()
    os.chdir(metadata_tmp)

    for series, image in images.iteritems():
        log.debug('Generating metadata for image [%s] [%s]', image.name, series)
        check_output(['juju', 'metadata', 'generate-image', '-i', image.id, '-s', series, '-d', metadata_tmp])

    os.chdir(os.path.join(metadata_tmp, 'images'))
    for filename in glob2.glob('**/*'):
        if os.path.isfile(filename):
            with open(filename) as fp:
                log.debug('Pushing file to Swift [%s]', filename)
                swift.put_object(container_name, filename, fp)

    log.debug('Cleaning up temporary files')
    os.chdir(cwd)
    shutil.rmtree(metadata_tmp)        

def main():
    parser = ArgumentParser()
    parser.add_argument('-c', '--config-file', default='config.yml')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--skip-bootstrap', action='store_true', help='Skip juju bootstrap')

    args = parser.parse_args()
    
    configure_logger(args.verbose)

    with open(args.config_file) as fp:
        config = yaml.load(fp)

    keystone = keystoneclient.v2_0.client.Client(
        auth_url=config['auth-url'],
        tenant_name=config['tenant-name'],
        username=config['username'],
        password=config['password'],
    )

    log.info('Authenticating with Keystone')

    auth_token = keystone.auth_token

    glance_endpoint = keystone.service_catalog.url_for(service_type='image')
    swift_endpoint = keystone.service_catalog.url_for(service_type='object-store')

    glance = glanceclient.v1.Client(glance_endpoint, token=auth_token)

    swift = swiftclient.client.Connection(
        preauthurl=swift_endpoint,
        preauthtoken=auth_token,
    )

    image_metadata_url = SWIFT_CONTAINER_URL_FORMAT.format(swift_endpoint, config['image-metadata-container'])
    prepare_environment(config, image_metadata_url)

    images = prepare_images(glance, config['series'])
    push_image_metadata(swift, config['image-metadata-container'], images)

    if not args.skip_bootstrap:
        check_call(['juju', 'bootstrap'])

if __name__ == '__main__':
    main()
