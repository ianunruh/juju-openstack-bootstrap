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

This tool does the following steps to prepare for Juju. It is based off of the [Set up a Private Cloud using Simplestreams](https://juju.ubuntu.com/docs/howto-privatecloud.html) guide.

1. Retrieve service catalog and token from Keystone
2. Prepare the `environments.yaml` file for the Juju client
3. Upload Ubuntu cloud images using Glance
4. Run `juju sync-tools`
5. Generate image metadata files using `juju metadata generate-image`
6. Upload generated image metadata using Swift
7. Run `juju bootstrap`

Juju creates and uses a container on Swift for metadata storage. This container is created when running `juju sync-tools` or `juju bootstrap`.
