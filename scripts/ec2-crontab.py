#!/usr/bin/env python
# coding: utf8

from __future__ import unicode_literals

import argparse
import json
import logging
import boto3
from botocore.exceptions import ProfileNotFound, ClientError
import os
from croniter import croniter
from datetime import datetime

def _init_aws_session(boto_profile='dev'):
    """Return a session to query AWS API

    :param boto_profile: name of the session profile
    :type boto_profile: string
    :return: Boto3 service client instance
    :rtype: boto3.session.Session
    """
    # Let's go
    try:
        if boto_profile:
            session = boto3.Session(profile_name=boto_profile)
        else:
            session = boto3.Session()
    except ProfileNotFound as e:
        logging.error(e)
        print e
        raise SystemExit, 1

    return session

def tag_to_date(value):
    ''' Transcode the value of a auto:* tag to a date function

    :param value: The value of the auto:* tag_to_date
    :type value: string
    :return: date of the event
    :rtype: datetime
    '''
    if value == 'now':
        return datetime.now()

    logging.error("Unable to transcode [%s] to a date!"
        " Event set in the futur." % value)
        
    return datetime.date(datetime.max)

def ec2_apply_cron(profile_name = False, id = False, dry_run = True):
    ''' Return the list of all instances matching filters

    :param id: Run only on a specific instances
    :type id: string
    :return: don't know yet, nb of changed, total ?
    :rtype: array ?
	'''
    logging.debug("+ Looking for all tagged instances")

    session = _init_aws_session(profile_name)  # Init a BOTO3 session
    ec2 = session.resource(u'ec2')

    # Retrieve EC2 instances stopped or running with handled tags
    Filters = [
        {
            'Name': 'tag-key',
            'Values': ['auto:stop', 'auto:start'],
        },
        {
            'Name': 'instance-state-name',
            'Values': ['stopped','running'],
        }
    ]

    if id:
        logging.debug("+ Finally, looking only for %s", id)
        Filters.append({
            'Name': 'instance-id',
            'Values': [id],
        })

    instances = ec2.instances.filter(Filters = Filters)
    instances_to_start = []
    instances_to_stop = []

    for instance in instances:
        logging.debug("+ Found [%s]" % instance.id)

        instance_start_at = datetime.date(datetime.max)
        instance_stop_at = instance_start_at

        if getattr(instance, 'state', False):
            instance_state = instance.state.get('Name')
        else:
            logging.error("Unable to get [%s] state" % instance.id)
            continue

        if instance_state != 'stopped' and instance_state != 'running':
            logging.error("[%s] has unsupported [%s] state" %
                (instance.id, instance_state))
            continue

        for tag in instance.tags:
            k = tag['Key'].decode('utf-8').lower()
            if k == 'auto:start':
                instance_start_at = tag_to_date(
                    tag['Value'].decode('utf-8').lower()
                )

            if k == 'auto:stop':
                instance_stop_at = tag_to_date(
                    tag['Value'].decode('utf-8').lower()
                )

        if instance_start_at == instance_stop_at:
            logging.error("%s is [%s] and must be up from: [%s] to [%s])!" %
                (instance.id, instance_state,
                instance_start_at, instance_stop_at)
            )
            continue

        logging.info("+ [%s] is [%s], wake at [%s]"
            " and stop at [%s]" %
            (instance.id, instance_state,
            instance_start_at, instance_stop_at)
        )

        # There is something to optimize there to avoid
        # all these calls... Build the list first and parse after ?
        current_date = datetime.now()

        if instance_state == "running":
            if current_date > instance_stop_at:
                logging.debug("++ I must stop it!")
                instances_to_stop.append(instance.id)

            continue

        if instance_state == "stopped":
            if current_date > instance_start_at:
                logging.debug("++ Wake up!")
                instances_to_start.append(instance.id)

            continue

        logging.error("Untrapped state [%s]" % instance_state)
        # continue

    output = {}
    if instances_to_start:
        output['to_start'] = instances_to_start
        try:
            result = ec2.instances.filter(
                Filters = [
                    {
                        'Name': 'tag-key',
                        'Values': ['auto:start'],
                    },
                    {
                        'Name': 'instance-id',
                        'Values': instances_to_start,
                    },
                ],
                DryRun = dry_run,
            ).start()
        except ClientError as e:
            if e.response['Error'].get('Code') == 'DryRunOperation':
                logging.debug(e.response['Error'])
            else:
                logging.error(e)
            output['start_result'] = e.response['Error'].get('Message')

    if instances_to_stop:
        output['to_stop'] = instances_to_stop
        try:
            result = ec2.instances.filter(
                Filters = [
                    {
                        'Name': 'tag-key',
                        'Values': ['auto:stop'],
                    },
                    {
                        'Name': 'instance-id',
                        'Values': instances_to_stop,
                    },
                ],
                DryRun = dry_run,
            ).stop()
        except ClientError as e:
            if e.response['Error'].get('Code') == 'DryRunOperation':
                logging.debug(e.response['Error'])
            else:
                logging.error(e)
            output['stop_result'] = e.response['Error'].get('Message')

    return json.dumps(output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description = """Start or stop an instance based on the value of
        auto:start and auto:stop tags.
        !!! BEWARE TZ and local time !!!
        """
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
        default = 'dev',
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

    parser.add_argument('--dry-run',
        help = 'do nothing',
        required = False,
        action = 'store_true',
        dest = 'dry_run',
        default = False,
    )

    args = parser.parse_args()

    if args.debug_mode:
        logging.basicConfig(level=logging.DEBUG)

    if not args.profile_name:
        args.profile_name = os.environ.get('AWS_PROFILE', False)

    if args.instance_id:
        logging.info("- Looking for: %s..." % args.instance_id)

    print ec2_apply_cron(args.profile_name, args.instance_id)
