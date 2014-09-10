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

def clean_environment():
    juju_env_path = os.path.expanduser('~/.juju/environments')
    if os.path.isdir(juju_env_path):
        shutil.rmtree(juju_env_path)

def prepare_environment(config):
    environments = {
        'default': 'openstack',
        'environments': {
            'openstack': {
                'type': 'openstack',
                'use-floating-ip': config['use-floating-ip'],
                'control-bucket': config['control-bucket'],
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

def clean_images(glance, series):
    for series_name, options in series.iteritems():
        clean_image(glance, options)

def clean_image(glance, options):
    for image in glance.images.list():
        if image.name == options['name']:
            log.info('Deleting image [%s]', image.name)
            image.delete()

            return

def prepare_images(glance, series):
    images = {}

    for series_name, options in series.iteritems():
        images[series_name] = prepare_image(glance, options)

    for image in images.itervalues():
        while image.status != 'active':
            log.info('Waiting 10 seconds for image to become active [%s] [%s]', image.name, image.status)
            time.sleep(10)

            image = glance.images.get(image.id)

    return images

def prepare_image(glance, options):
    for image in glance.images.list():
        if image.name == options['name']:
            log.debug('Image already exists [%s]', image.name)
            return image

    log.debug('Creating image [%s]', options['name'])

    return glance.images.create(
        name=options['name'],
        disk_format=options.get('disk-format', 'qcow2'),
        container_format=options.get('container-format', 'bare'),
        min_disk=options.get('min-disk', '8'),
        min_ram=options.get('min-ram', '256'),
        copy_from=options['url'],
    )

def clean_container(swift, control_bucket):
    try:
        log.info('Looking for existing container [%s]', control_bucket)
        container, objects = swift.get_container(control_bucket, full_listing=True)

        for o in objects:
            log.info('Deleting object [%s]', o['name'])
            swift.delete_object(control_bucket, o['name'])

        log.info('Deleting container [%s]', control_bucket)
        swift.delete_container(control_bucket)
    except:
        pass

def push_image_metadata(swift, control_bucket, images):
    cwd = os.getcwd()

    metadata_tmp = tempfile.mkdtemp()
    os.chdir(metadata_tmp)

    for series, image in images.iteritems():
        log.debug('Generating metadata for image [%s] [%s]', image.name, series)
        check_output(['juju', 'metadata', 'generate-image', '-i', image.id, '-s', series, '-d', metadata_tmp])

    for filename in glob2.glob('**/*'):
        if os.path.isfile(filename):
            with open(filename) as fp:
                log.debug('Pushing file to control bucket [%s]', filename)
                swift.put_object(control_bucket, filename, fp)

    log.debug('Cleaning up temporary files')
    os.chdir(cwd)
    shutil.rmtree(metadata_tmp)

def main():
    parser = ArgumentParser()
    parser.add_argument('-c', '--config-file', default='config.yml')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--skip-bootstrap', action='store_true', help='Skip juju bootstrap')
    parser.add_argument('--clean-control-bucket', action='store_true', help='Remove existing control bucket')
    parser.add_argument('--clean-images', action='store_true', help='Remove existing Juju images')
    parser.add_argument('--clean-environment', action='store_true', help='Remove Juju environments directory')
    parser.add_argument('--clean-all', action='store_true', 'Clean everything')

    args = parser.parse_args()

    if args.clean_all:
        args.clean_control_bucket = True
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

    log.info('Authenticating with Keystone')

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
    if args.clean_control_bucket:
        clean_container(swift, config['control-bucket'])
    if args.clean_images:
        clean_images(glance, config['series'])

    prepare_environment(config)
   
    log.info('Running juju sync-tools')
    check_call(['juju', 'sync-tools'])

    images = prepare_images(glance, config['series'])
    push_image_metadata(swift, config['control-bucket'], images)

    if not args.skip_bootstrap:
        check_call(['juju', 'bootstrap'])

if __name__ == '__main__':
    main()
