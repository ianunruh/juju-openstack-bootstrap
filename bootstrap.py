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

SWIFT_CONTAINER_HEADERS = {
    'X-Container-Read': '.r:*'
}

LOG = logging.getLogger(__name__)

def main():
    parser = ArgumentParser()
    parser.add_argument('-c', '--config-file', default='config.yml')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--skip-bootstrap', action='store_true', help='Skip juju bootstrap')
    parser.add_argument('--clean-container', action='store_true', help='Remove existing control bucket')
    parser.add_argument('--clean-images', action='store_true', help='Remove existing Juju images')
    parser.add_argument('--clean-environment', action='store_true', help='Remove Juju environments directory')
    parser.add_argument('--clean-all', action='store_true', help='Clean everything')

    args = parser.parse_args()

    if args.clean_all:
        args.clean_container = True
        args.clean_images = True
        args.clean_environment = True
    
    configure_logger(args.verbose)

    with open(args.config_file) as fp:
        config = yaml.load(fp)

    keystone = keystoneclient.v2_0.client.Client(
        auth_url=config['auth-url'],
        tenant_name=config['tenant-name'],
        username=config['username'],
        password=config['password'],
    )

    LOG.info('Authenticating with Keystone')

    auth_token = keystone.auth_token

    glance_endpoint = keystone.service_catalog.url_for(service_type='image')
    swift_endpoint = keystone.service_catalog.url_for(service_type='object-store')

    glance = glanceclient.v1.Client(glance_endpoint, token=auth_token)

    swift = swiftclient.client.Connection(
        preauthurl=swift_endpoint,
        preauthtoken=auth_token,
    )

    if args.clean_environment:
        clean_environment()
    if args.clean_container:
        clean_container(swift, config['container-name'])
    if args.clean_images:
        clean_images(glance, config['series'])

    image_metadata_url = '{}/{}/images'.format(swift_endpoint, config['container-name'])
    swift.put_container(config['container-name'], SWIFT_CONTAINER_HEADERS)
    
    prepare_environment(config, image_metadata_url)

    images = prepare_images(glance, config['series'])
    push_image_metadata(swift, config['container-name'], images)

    LOG.debug('Validating image metadata')
    check_output(['juju', 'metadata', 'validate-images'])

    if not args.skip_bootstrap:
        LOG.debug('Bootstrapping Juju')
        check_call(['juju', 'bootstrap'])

def configure_logger(verbose=False):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(handler)

    if verbose:
        LOG.setLevel(logging.DEBUG)
    else:
        LOG.setLevel(logging.WARN)

def clean_environment():
    path = os.path.expanduser('~/.juju/environments/openstack.jenv')
    if os.path.exists(path):
        os.remove(path)

def prepare_environment(config, image_metadata_url):
    environments = {
        'default': 'openstack',
        'environments': {
            'openstack': {
                'type': 'openstack',
                'use-floating-ip': config['use-floating-ip'],
                'image-metadata-url': image_metadata_url,
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

    LOG.debug('Creating Juju environment config')
    with open(juju_env_path, 'w') as fp:
        yaml.dump(environments, fp, default_flow_style=False)

def clean_images(glance, series):
    for series_name, options in series.iteritems():
        clean_image(glance, options)

def clean_image(glance, options):
    for image in glance.images.list():
        if image.name == options['name']:
            LOG.info('Deleting image [%s]', image.name)
            image.delete()

            return

def prepare_images(glance, series):
    images = {}

    for series_name, options in series.iteritems():
        images[series_name] = prepare_image(glance, options)

    for image in images.itervalues():
        while image.status != 'active':
            LOG.info('Waiting 10 seconds for image to become active [%s] [%s]', image.name, image.status)
            time.sleep(10)

            image = glance.images.get(image.id)

    return images

def prepare_image(glance, options):
    for image in glance.images.list():
        if image.name == options['name']:
            LOG.debug('Image already exists [%s]', image.name)
            return image

    LOG.debug('Creating image [%s]', options['name'])

    return glance.images.create(
        name=options['name'],
        disk_format=options.get('disk-format', 'qcow2'),
        container_format=options.get('container-format', 'bare'),
        min_disk=options.get('min-disk', '8'),
        min_ram=options.get('min-ram', '256'),
        copy_from=options['url'],
    )

def clean_container(swift, container_name):
    try:
        LOG.info('Looking for existing container [%s]', container_name)
        container, objects = swift.get_container(container_name, full_listing=True)

        for obj in objects:
            LOG.info('Deleting object [%s]', obj['name'])
            swift.delete_object(container_name, obj['name'])

        LOG.info('Deleting container [%s]', container_name)
        swift.delete_container(container_name)
    except:
        pass

def push_image_metadata(swift, container_name, images):
    cwd = os.getcwd()

    metadata_tmp = tempfile.mkdtemp()

    try:
        os.chdir(metadata_tmp)

        for series, image in images.iteritems():
            LOG.debug('Generating metadata for image [%s] [%s]', image.name, series)
            check_output(['juju', 'metadata', 'generate-image', '-i', image.id, '-s', series])

        for filename in glob2.glob('**/*'):
            if os.path.isfile(filename):
                with open(filename) as fp:
                    LOG.debug('Pushing file to control bucket [%s]', filename)
                    swift.put_object(container_name, filename, fp)

        LOG.debug('Cleaning up temporary files')
    finally:
        os.chdir(cwd)
        shutil.rmtree(metadata_tmp)

if __name__ == '__main__':
    main()
