#!/usr/bin/env python
# coding: utf8

from __future__ import unicode_literals
import argparse
import json
import logging
import boto3
from botocore.exceptions import ProfileNotFound
import os

'''
-------------------------------------------------------------------------------
# Establish a session with AWS
#
-------------------------------------------------------------------------------
'''


def _init_aws_session(boto_profile='int'):
    # Let's go
    try:
        session = boto3.Session(profile_name=boto_profile)
    except ProfileNotFound as e:
        logging.error(e)
        print
        e
        raise SystemExit, 1

    return session


'''
-------------------------------------------------------------------------------
#
# http://docs.ansible.com/ansible/developing_inventory.html
-------------------------------------------------------------------------------
'''
def instances_get(id=None, states=None):
    ''' instances_get()

    Return the list of all instances matching filters
	'''
    logging.debug("+ Looking for all running instances")

    session = _init_aws_session()  # Init a BOTO3 session
    ec2 = session.resource(u'ec2')
    fields=["id", "tags", "key_name"]

    Filters = []

    if id is not None:
        logging.debug("+ Finally, looking only for %s", id)
        Filters.append({
            'Name': 'instance-id',
            'Values': [id],
        })

    if states is not None:
        logging.debug("+ I search %s instances" % states)
        Filters.append({
            'Name': 'instance-state-name',
            'Values': states,
        })

    instances = ec2.instances.filter(Filters=Filters)

    ansible_inventory = {"_meta": {"hostvars": {}}}

    for instance in instances:
        logging.debug("+Found %s" % instance.id)

        if instance.tags and instance.private_ip_address:
            instance_vars = {}

            # parse each key and reformat some
            for tag in instance.tags:
                # deja crade... :'(
                k = tag['Key'].decode('utf-8').lower()
                key = {
                    "asg": u"role", # To be removed
                    "role": u"role",
                    "squidport": u"squid_port",
                    "squidwithssl": u"squid_ssl",
                    "squidwithantivirus": u"squid_antivirus",
                    "proxyprotocol": u'squid_proxy_protocol',
                    "squidconfigfile": u"squid_config_file",
                }.get( k, u"ec2_" + k )

                value = tag['Value'].decode('utf-8').lower()

                instance_vars[key] = value

            # Add some attributes
            for a in ['private_dns_name', 'public_dns_name', 'image_id', ]:
                if getattr(instance, a, False):
                        instance_vars[u'ec2_' + a] = getattr(instance, a).decode('utf-8')

            # Placement is an array I don't want
            if instance.placement:
                instance_vars[u'ec2_availabilityzone'] = \
                    instance.placement['AvailabilityZone'].decode('utf-8')
                instance_vars[u"ec2_region"] = instance_vars["ec2_availabilityzone"][:-1]

            # Must specify full path of key file
            if instance.key_name:
                instance_vars[u"ansible_ssh_private_key_file"] = \
                    u"~/.ssh/%s.pem" % instance.key_name.decode('utf-8')

            # Ansible use private_ip_address. If not there, instance can't be added
            instance_vars[u"ec2_private_ip_address"] = instance_vars[u"ansible_host"] = \
                instance.private_ip_address.decode('utf8')

            # Default user name for ansible is ec2-user
            instance_vars[u"ansible_user"] = {
                "ami-64bb2317": u"gtsadmin",    # RET, eu-west-1
                "ami-67fd0908": u"gtsadmin",    # RET, eu-central-1
                "ami-98345feb": u"admin",       # FortiOS custom, eu-west-1
                "ami-87e91fe8": u"admin",       # FortiOS custom, eu-central-1
                "ami-8af48ef9": u"admin",       # BigIP, eu-west-1
                "ami-fbeb9188": u"admin",
                "ami-cbf58fb8": u"admin",
                "ami-c8f58fbb": u"admin",
                "ami-51f18b22": u"admin",
                "ami-7bf38908": u"admin",
                "ami-b5f68cc6": u"admin",
                "ami-65f58f16": u"admin",
                "ami-91f18be2": u"admin",
                "ami-2157aa4e": u"admin",       # BigIP, eu-central-1
                "ami-8055a8ef": u"admin",
                "ami-2c56ab43": u"admin",
                "ami-2f57aa40": u"admin",
                "ami-2854a947": u"admin",
                "ami-2657aa49": u"admin",
                "ami-e357aa8c": u"admin",
                "ami-2557aa4a": u"admin",
                "ami-cb55a8a4": u"admin",
                "ami-082a4d7b": u"admin",       # BigIP custom, eu-west-1
            }.get( getattr( instance, "image_id", None), u"ec2-user" )


            # Build groups named after list values
            for g in ["role", "ec2_aws:cloudformation:stack-name"]:
                # Instance has a label/key named as g
                if instance_vars.get(g, False):

                    # If needed Create group in inventory
                    if not ansible_inventory.get(instance_vars[g]):
                        logging.warning("Create group %s" % instance_vars[g])
                        ansible_inventory[instance_vars[g]] = {'hosts': []}

                    ansible_inventory[instance_vars[g]]['hosts'].append(instance.id)
                    logging.warning("adding %s to group %s" % (instance.id, instance_vars[g]) )

            # Add this instance to global inventory
            ansible_inventory['_meta']['hostvars'].update(
                { instance.id: instance_vars }
            )
        else:
            logging.warning("%s has no tag or no private ip (skipped)" % instance.id)

    # end for instance in instances

    return ansible_inventory


def instance_get(id=None, fields=["id", "state"]):
    ''' instance_get( instanceId)

	Return the state of the instance specified by id
	'''

    return instances_get(id=id, fields=fields)




'''
-------------------------------------------------------------------------------
-------------------------------------------------------------------------------
'''
if __name__ == '__main__':
    # Take care of the command line
    parser = argparse.ArgumentParser(
        description = """Start or stop an instance based on the value of
        auto:start and auto:stop tags"""
    )

    parser.add_argument(
        '-p', '--profile',
        help = 'AWS profile to use.'
             ' If not set or if the script is run from Ansible,'
             ' please set AWS_PROFILE. If both are specified,'
             ' the one in the cmd line is used.',
        required = False,
        action = 'store',
        dest = 'profile_name',
        default = 'int',
    )

    parser.add_argument(
        '-i', '--instance',
        help = 'Only on specified instance',
        required = False,
        action = 'store',
        dest = 'instance_id',
        default = False,
    )

    parser.add_argument('--debug',
        help = 'set maximum verbosity',
        required = False,
        action = 'store_true',
        dest = 'debug_mode',
        default = False,
    )

    args = parser.parse_args()

    if args.debug_mode:
        logging.basicConfig(level=logging.DEBUG)

    if not args.profile_name:
        args.PROFILENAME = os.environ.get('AWS_PROFILE', False)

    if args.instance_id:
        logging.info("- Looking for: %s..." % args.instance_id)



    logging.info("- Building inventory for all filtered EC2")
    #_build_inventory(args.PROFILENAME)
    #print json.dumps(instances_get())
