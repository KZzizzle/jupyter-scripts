import sys, os
from optparse import OptionParser
import docker
import json

def main(argv):
    '''
        This script create a docker image. It should be called from the following 
        directory structure:

            - sparc-internal/services/group/model_name/
                Dockerfile
                labels/
                    input.json
                    output.json
                    info.json
                    settings.json

        in which a Dockerfile should be present

        The script takes the following arguments

        --dockerfile    dockerfile name (str)
        --registry:     url for registry (str)
        --namespace:    Namespace for docker image (str)
        --imagename:    Name for docker image (str)
        --version:      Version for docker image (str)
        --publish:      Push to registry (bool)

        registry is optional, publish defaults to True

        images will be tagged as follows:

        registry/namespace/imagename:version

        Examples:

        1.  dockerize --namespace=simcore/services/comp --imagename=sleeper --version=1.0  

        creates simcore/services/comp/sleeper:1.0

        2. dockerize --registry=simcore.io --namespace=simcore/services/comp --imagename=sleeper --version=1.0  

        creates simcore.io/simcore/services/comp/sleeper:1.0

        The script looks up all json files in the labels directory and labels the image accordingly


    '''
    parser = OptionParser()

    parser.add_option(
        "-d", "--dockerfile", dest="dockerfile", help="docker file to use")
    parser.add_option(
        "-r", "--registry", dest="registry", help="docker registry to use")
    parser.add_option(
        "-n", "--namespace", dest="namespace", help="which namespace to use")
    parser.add_option(
        "-i", "--imagename", dest="imagename", help="name for the image")
    parser.add_option(
        "-v", "--version", dest="version", help="version for the image")

    parser.add_option(
        "-p", "--publish", action="store_true", dest="publish", help="publish in registry")


    (options, _args) = parser.parse_args(sys.argv)

    # we should have a name, a version and a namespace
    if not options.imagename:
        parser.error('Image name not given')
    if not options.version:
        parser.error('Version not given')
    if not options.namespace:
        parser.error('Namespace not given')

    if options.publish:
        if not options.registry:
            parser.error('Registry for publishing image not given')

    dockerfile = "Dockerfile"
    if options.dockerfile:
        dockerfile = options.dockerfile


    model_root_path = os.getcwd()
    label_path = os.path.join(model_root_path, "labels")
    
    labels = {}
    for file in os.listdir(label_path):
        if file.endswith(".json"):
            json_file = os.path.join(label_path, file)
            label_name = os.path.splitext(file)[0]
            with open(json_file) as json_data:
                label_dict = json.load(json_data)
                # TODO: Validate label dict syntax
                labels["io.simcore."+label_name] = json.dumps(label_dict)

    tag = ''
    if options.registry:
        tag = options.registry + "/"

    tag = tag + options.namespace + "/"
    tag = tag + options.imagename
    tag = tag + ":" + options.version

    client = docker.from_env(version='auto')
  
    print(model_root_path, tag, labels, dockerfile)

    if labels:
        client.images.build(path=model_root_path, tag=tag, labels=labels, dockerfile=dockerfile)
    else:
        client.images.build(path=model_root_path, tag=tag, dockerfile=dockerfile)
    
    if options.publish:
        #client.login(registry=options.registry, username="z43", password="z43")
        for line in client.api.push(tag, stream=True):
            print(line)

if __name__ == "__main__":
    main(sys.argv[1:])
