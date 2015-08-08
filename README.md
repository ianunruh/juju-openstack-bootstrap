## juju-openstack-bootstrap

Quick and easy way to get Juju running on a private OpenStack cloud

1. Edit `config.yml` for your environment
2. Run `vagrant up`

Afterwards, you can use the Juju client like so.

```bash
vagrant ssh

sudo -i
juju status
```

That's it!

### Requirements

* Modern version of Vagrant
* OpenStack (Swift and Glance)

### Process

This tool does the following steps to prepare for Juju. It is based off of the [Set up a Private Cloud using Simplestreams](https://jujucharms.com/docs/stable/howto-privatecloud) guide.

1. Retrieve service catalog and token from Keystone
2. Prepare the `environments.yaml` file for the Juju client
3. (optional) Delete the metadata container if it exists
4. (optional) Delete any existing images if they exist
5. Upload Ubuntu cloud images using Glance
6. Generate image metadata files using `juju metadata generate-image`
7. Upload generated image metadata to the metadata container
8. Run `juju bootstrap`

Juju creates and uses a container on Swift for image metadata. This container is created when running `juju sync-tools` or `juju bootstrap`.
