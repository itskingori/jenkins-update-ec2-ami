#!/usr/bin/env python

import requests
import os
import boto.ec2
import sys
import re
import time

build_url = os.environ['BUILD_URL']
jenkins_base_url = os.environ['JENKINS_URL']
jenkins_api_username = os.environ['JENKINS_API_USERNAME']
jenkins_api_token = os.environ['JENKINS_API_TOKEN']
jenkins_crumb_header_name = ""
jenkins_crumb_header_value = ""
verify_ssl = True
aws_region = os.getenv('AWS_REGION', 'eu-west-1')
ec2_cloud_instance = os.getenv('EC2_CLOUD_INSTANCE', 'JenkinsEC2')
ami_profile_name = os.getenv('AMI_PROFILE_NAME', 'Ubuntu')
output_error_string = os.getenv('OUTPUT_ERROR_STRING', 'Error:')
build_output_text = ""

def get_crumb_url():
    request_url = jenkins_base_url.replace('https://', '');
    if not request_url.endswith('/'):
        request_url = '%s/' % request_url
    return 'https://%s:%s@%scrumbIssuer/api/json' % (
            jenkins_api_username,
            jenkins_api_token,
            request_url)

def get_jenkins_crumb():
    global jenkins_crumb_header_name
    global jenkins_crumb_header_value

    if jenkins_crumb_header_value:
        return jenkins_crumb_header_value

    crumb_url = get_crumb_url()
    r = requests.get(crumb_url, verify=verify_ssl)
    jenkins_crumb_header_name = r.json()["crumbRequestField"]
    jenkins_crumb_header_value = r.json()["crumb"]
    return jenkins_crumb_header_value

def get_jenkins_build_output():
    global build_url
    global build_output_text

    if build_output_text:
        return build_output_text

    build_url = build_url.replace('https://', '');
    if not build_url.endswith('/'):
        build_url = '%s/' % build_url

    loop = True
    start = 0
    headers = {jenkins_crumb_header_name: jenkins_crumb_header_value}
    while loop:
        jenkins_url = 'https://%s:%s@%slogText/progressiveText?start=%s' % (
            jenkins_api_username,
            jenkins_api_token,
            build_url,
            start)
        r = requests.get(jenkins_url, verify=verify_ssl,  headers=headers)
        if not r.status_code == 200:
            print 'HTTP POST to Jenkins URL %s resulted in %s' % (jenkins_url, r.status_code)
            print r.headers
            print r.text
            sys.exit(1)

        # The X-Text-Size is confusing but it's more of a pointer than a size
        # thing. So we'll name the variable appropriately here to avoid
        # confusion.
        next_start = r.headers.get('X-Text-Size')
        more_data = r.headers.get('X-More-Data')

        print "Fetched logs ... start: %s, next-start: %s, more-data: %s" % (start, next_start, more_data)

        if start != next_start:
            build_output_text += r.text
        start = next_start

        regex = re.compile(r'(.*%s.*)' % "=== Script Configuration ===", re.MULTILINE)
        matches = [m.groups() for m in regex.finditer(r.text)]
        if matches:
            print "Fetched all the packer build output  -- moving on"
            loop = False
        else:
            loop = more_data

        time.sleep(5)

    return build_output_text

def get_error_lines(build_output):
    retval = ""
    regex = re.compile(r'(.*%s.*)' % output_error_string, re.MULTILINE)
    matches = [m.groups() for m in regex.finditer(build_output)]
    if matches:
        retval = "**************************************************\n"
        retval += " Error string: '%s'\n" % output_error_string
        retval += " Found the following errors in the build output\n"
        retval += "**************************************************\n"
        for m in matches:
            retval += '%s\n' % m[0]
        retval += "**************************************************\n"
    return retval

def get_packer_ami_id(build_output):
    regex = re.compile(r'.*amazon-ebs: AMIs were created.*\n.*(ami-.*)$', re.MULTILINE)
    matches = [m.groups() for m in regex.finditer(build_output)]
    for m in matches:
        print "Matched %s in build output" % m[0].strip()
        return m[0].strip()

def delete_ami(ami_id):
    ec2_conn = boto.ec2.connect_to_region(aws_region)
    ec2_conn.deregister_image(ami_id, delete_snapshot=True)

def get_groovy_url():
    groovy_url = jenkins_base_url.replace('https://', '')
    if not groovy_url.endswith('/'):
        groovy_url = '%s/' % groovy_url
    return 'https://%s:%s@%sscriptText' % (
            jenkins_api_username,
            jenkins_api_token,
            groovy_url)

def get_jenkins_ami_id():
    groovy_url = get_groovy_url()
    groovy_script = """
        def foundAmi = ""
        Jenkins.instance.clouds.each {
          if (it.displayName == '%s') {
            it.getTemplates().each {
              if (it.getDisplayName().toLowerCase().contains("%s".toLowerCase())) {
                // By definition, this will return the last result it finds
                // You better make sure you supply a unique ami_profile_name ;)
                foundAmi = it.getAmi();
              }
            }
          }
        }
        println(foundAmi)
        """ % (ec2_cloud_instance, ami_profile_name)
    payload = {'script': groovy_script}
    headers = {jenkins_crumb_header_name: jenkins_crumb_header_value}
    r = requests.post(groovy_url, verify=verify_ssl, data=payload, headers=headers)
    if not r.status_code == 200:
        print 'HTTP POST to Jenkins URL %s resulted in %s' % (groovy_url, r.status_code)
        print r.headers
        print r.text
        sys.exit(1)

    return r.text.strip()

def update_jenkins_ami_id(ami_id):
    groovy_url = get_groovy_url()
    groovy_script = """
        def foundAmi = ""
        Jenkins.instance.clouds.each {
          if (it.displayName == '%s') {
            it.getTemplates().each {
              if (it.getDisplayName().toLowerCase().contains("%s".toLowerCase())) {
                // By definition, this will update all the results it finds
                // You better make sure you supply a unique ami_profile_name ;)
                it.setAmi("%s")
                foundAmi = "yes"
              }
            }
          }
        }
        Jenkins.instance.save()
        println(foundAmi)
        """ % (ec2_cloud_instance, ami_profile_name, ami_id)
    payload = {'script': groovy_script}
    headers = {jenkins_crumb_header_name: jenkins_crumb_header_value}
    r = requests.post(groovy_url, verify=verify_ssl, data=payload, headers=headers)
    if not r.status_code == 200:
        print 'HTTP POST to Jenkins URL %s resulted in %s' % (groovy_url, r.status_code)
        print r.headers
        print r.text
        sys.exit(1)

    return r.text.strip() == "yes"

def main():
    # Very high level overview of how this is supposed to work:
    # ---------------------------------------------------------
    # Get the Jenkins build output and check for errors
    #   - If there were errors,
    #       - delete the ami that was created
    #       - fail the build
    #   - If there were no errors,
    #       - Update Jenkins with the newly created AMI ID
    #       - Delete the old AMI in AWS
    #       - Pass the build

    print "=== Script Configuration ==="
    print "build_url: %s" % build_url
    print "jenkins_base_url: %s" % jenkins_base_url
    print "ami_profile_name: %s" % ami_profile_name
    print "aws_region: %s" % aws_region
    print "ec2_cloud_instance: %s" % ec2_cloud_instance

    get_jenkins_crumb()

    print "=== Script Results ==="

    # Check if there are any errors in the build output and get the ID of the
    # AMI that we just built with Packer from the build output
    error_lines = get_error_lines(get_jenkins_build_output())
    packer_ami_id = get_packer_ami_id(get_jenkins_build_output())
    if error_lines:
        print error_lines
        print "Deleting newly created AMI %s" % packer_ami_id
        delete_ami(packer_ami_id)
        sys.exit(1)
    if not packer_ami_id:
        print "Could not find the AMI we just built, unable to continue"
        sys.exit(1)
    print "Packer AMI ID set to: %s" % packer_ami_id

    # Get the AMI currently set on Jenkins right now (that we want to replace)
    old_jenkins_ami_id = get_jenkins_ami_id()
    if not old_jenkins_ami_id:
        print "Could not find (current) Jenkins AMI ID -- moving on"

    print "New ID: %s, Old ID: %s" % (packer_ami_id, old_jenkins_ami_id)

    update_success = update_jenkins_ami_id(packer_ami_id)
    if update_success:
        print "Jenkins AMI has been updated to %s" % packer_ami_id
    else:
        print "Ran into an error when attempting to update the Jenkins AMI ID"
        print "Deleting newly created AMI %s" % packer_ami_id
        delete_ami(packer_ami_id)
        sys.exit(1)

    if old_jenkins_ami_id:
        print "Deleting previous Jenkins AMI %s in AWS" % old_jenkins_ami_id
        delete_ami(old_jenkins_ami_id)

if __name__ == '__main__':
    main()
