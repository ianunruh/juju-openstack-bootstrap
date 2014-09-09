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
