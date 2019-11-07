# jenkins-update-ec2-ami

Automate building of the Jenkins EC2 AMI

## Usage

In a Jenkinsfile:

```groovy
node {
 sh './packer build -color=false jenkins_agent_ami.json'
 sh 'JENKINS_API_USERNAME="packer" JENKINS_API_TOKEN="SECRETPASSWORD" python update-ec2-ami.py'
}
```

`EC2_CLOUD_INSTANCE` is the name of the Amazong EC2 cloud in the plugin (as seen in the screenshot below).
`AMI_PROFILE_NAME` is the AMI’s “Description” in the EC2 plugin.

Detailed instructions: https://blog.grakn.ai/automated-aws-ami-builds-for-jenkins-agents-with-packer-e569630b1f8e

## Credits

* Copied from https://gist.github.com/marvinpinto/a6c9b5119d418a65d489
* Originated from https://github.com/jenkinsci/ec2-plugin/pull/154
