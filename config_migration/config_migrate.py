
import traceback
import requests
import sys, json
import os
import argparse
import time
import traceback
import logging
import copy
import concurrent.futures
import base64
import logging.handlers
import time
import ipaddress

# Log handlers that need to be saved from call to call
file_log_handler = None
console_log_handler = None

class migration(object):
    def __init__(self, source, adm_type, adm_ip, adm_username, adm_password, adm_svc_url, adm_svc_client_id, adm_svc_client_secret, operation, sourceType, target='', vservers=None, passwords=None):
        # ADM details
        self.adm_type = adm_type
        self.adm_ip = adm_ip
        self.adm_username = adm_username
        self.adm_password = adm_password
        self.adm_svc_url = adm_svc_url
        self.adm_svc_client_id = adm_svc_client_id
        self.adm_svc_client_secret =  adm_svc_client_secret
        self.target = target
        self.sourceType = sourceType
        self.tenant_name = ''

        self.operation = operation
        self.protocol = 'http'
        self.basepath = '/stylebook/nitro/v2/config'
        self.endpoint = '/adc_configs/actions'
        self.sessionid = None
        
        self.source = source
        self.vservers = vservers if vservers is not None else "data/discovered_vservers.json"
        self.selectedvservers = "data/selected_vservers.json"
        self.passwords = passwords if passwords is not None else "data/migrateconfig.json"
        self.log_file = f"log/{int(time.time())}_migration.txt"

        # API related details
        self.vservers_list = []
        self.target_id = None
        self.source_id = None
        self.cli_commands = None
        self.configpackid = None
        self.error = None

        # extract_vservers_config API payload
        self.targetNS_to_vservers_mapping = []

        # threading
        self.max_threads = 10

        self.setup_logging()
    
    def perform_extract_vservers_operation(self):
        if self.sourceType == 'netscaler':
            self.source_id = self.fetch_device_id(self.source)
            self.target_id = self.source_id
        else:
            self.target_id = self.fetch_device_id(self.target)

        api_payload = self.create_extract_vservers_payload()
        api_response = self.extract_vservers(api_payload)
        vservers_response_data = api_response.get('vservers', [])
        self.write_to_vservers_file(vservers_response_data)
        extract_vservers_response = self.print_info(stage_number=1)

    def perform_extract_vservers_config_operation(self):
        self.create_targetNS_to_vservers_mapping()
        self.remove_migration_data()
        vservers = self.targetNS_to_vservers_mapping['vservers']
        if self.sourceType == 'netscaler':
            self.source_id = self.fetch_device_id(self.source)
            self.target_id = self.source_id
        else:
            self.target_id = self.fetch_device_id(self.target)
        api_payload = self.create_extract_vservers_config_payload(vservers)
        vserver_names = [vserver['vserver_name'] for vserver in vservers]
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future = executor.submit(self.extract_vservers_config, api_payload, vserver_names)
            try:
                # Get the result of the API call
                result = future.result()
                if result is not None:
                    self.logger.info('Successfully Extracted the Vserver specific configuration')
                    self.save_extract_vservers_config_data(result)
                    self.print_files_and_password_details()
                    self.print_info(stage_number=2)
                else:
                    self.logger.critical('Failed to extract the Vserver specific configuration')
            except Exception as e:
                raise e
    
    def perform_migrate_vservers_config_operation(self):
        # we can store this info so we don't to process it all the time
        self.create_targetNS_to_vservers_mapping()
        vservers = self.targetNS_to_vservers_mapping['vservers']
        self.target_id = self.fetch_device_id(self.target)
        if self.sourceType == 'netscaler':
            self.source_id = self.fetch_device_id(self.source)
        application_config = []
        file_uploads = []
        password_attributes = []
        application_config, file_uploads, password_attributes = self.create_file_uploads_and_passwords_payload(self.target)
        api_payload = self.create_migrate_vservers_config_payload(application_config, vservers, file_uploads, password_attributes)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future = executor.submit(self.migrate_vservers_config, api_payload)
            try:
                # Get the result of the API call
                result = future.result()
                if result is not None:
                    self.logger.info(f'Successfully Migrated the Vservers to Target NetScaler - {target}')
            except Exception as e:
                raise e

    def perform_operation(self):
        try:
            # logging in to adm
            self.login_to_adm()
        except Exception as e:
            return

        try:
            if self.sourceType == 'file':
                self.get_cli_commands()
            
            # Extract vservers operation
            if operation == 'extract_vservers':
                self.perform_extract_vservers_operation()

            # Extract vserver specific configuration
            if operation == 'extract_vservers_config':
                self.perform_extract_vservers_config_operation()

            # Migrate the vserver specific configuration to the Target NetScalers
            if operation == 'migrate_vservers_config':
                self.perform_migrate_vservers_config_operation()

        except Exception as e:
            self.logger.critical(f"Error in performing the {operation} operation")
        finally:
            self.logout_from_adm()

    def create_file_log_handler(self, file_name, log_level):
        # create file handler and roll logs if needed
        folder_path = os.path.dirname(file_name)

        # Check if the folder exists, if not create it
        if folder_path and not os.path.exists(folder_path):
            os.makedirs(folder_path)

        # Check if the file exists, if not create it
        if not os.path.exists(file_name):
            with open(file_name, 'w'):
                pass  # This creates an empty file
        
        file_handler = logging.handlers.RotatingFileHandler(file_name,
                                                            mode='a',
                                                            backupCount=0)
        # Do rollover if the file exists
        if os.path.isfile(file_name):
            file_handler.doRollover()
        
        # Set the file log handler level
        file_handler.setLevel(log_level)
        
        # Create formatters and add them to the handlers
        fh_format = logging.Formatter('%(asctime)s: %(levelname)s - %(message)s')
        file_handler.setFormatter(fh_format)
        
        return file_handler

    def setup_logging(self):
        try:
            global file_log_handler
            global console_log_handler
            # create logger
            self.logger = logging.getLogger()
            self.logger.setLevel(logging.DEBUG)
            # if called multiple times, remove existing handlers
            self.logger.removeHandler(file_log_handler)
            self.logger.removeHandler(console_log_handler)
            # create file handler
            file_log_handler = self.create_file_log_handler(self.log_file, logging.INFO)
            # add the handlers to the logger
            self.logger.addHandler(file_log_handler)

            # create console handler that sees even info messages
            console_log_handler = logging.StreamHandler()
            console_log_handler.setLevel(logging.INFO)
            ch_format = logging.Formatter('%(levelname)s - %(message)s')
            console_log_handler.setFormatter(ch_format)
            self.logger.addHandler(console_log_handler)
        except Exception as e:
            self.logger.critical(f'Error in setting up the logger: {str(e)}')
            return

    def get_onprem_header(self, sessionid, login_token):
        return {
            'Content-type':'application/json',
            'Accept':'*/*',
            'Cookie':'SESSID={}'.format(sessionid),
            'Connection': 'keep-alive',
            'rand_key': login_token,
            'NITRO_WEB_APPLICATION': 'true'
        }

    def get_service_header(self, sessionid, isCloud):
        return {
                'Content-type': 'application/json',
                'Accept':'*/*',
                'Cookie': 'SESSID={}'.format(sessionid),
                'Connection': 'keep-alive',
                'isCloud': '{}'.format(isCloud)
        }

    def fetch_device_id(self, target):
        try:
            if self.adm_type == 'service':
                protocol = 'https'
                headers = self.get_service_header(self.sessionid, 'True')
                url = "{}://{}/nitro/v1/config/ns?filter=ip_address:{}".format(protocol, self.adm_svc_url, target)
            else:
                protocol = 'http'
                headers = self.get_onprem_header(self.sessionid, '')
                url = "{}://{}/nitro/v1/config/ns?filter=ip_address:{}".format(protocol, self.adm_ip, target)
            r = self.do_get(url, headers)
            self.logger.info(r.status_code)
            out = r.json()
            target_id = out['ns'][0]['id']
            self.logger.info(f"NetScaler {target} found with ID: {target_id}")
        except BaseException as e:
            self.logger.critical(
                f"NetScaler {target} not found. Check if it is added in ADM")
            raise e
        if out['ns'][0]['instance_state'] == "Down":
            self.logger.critical(f"NetScaler {target} is in Down state. Please check the state of the NetScaler")
            raise e
        else:
            return target_id
            
    def do_get(self, url, headers):
        i = 0
        reattempt_count = 5
        while True:
            try:
                r = requests.get(url, headers=headers)
                if r.status_code == 401:
                    self.logger.info("Session expired. Will relogin")
                    sessionid = self.login_to_adm()
                    if adm_type == 'service':
                        headers = self.get_service_header(sessionid, 'true')
                    else:
                        headers = self.get_onprem_header(sessionid, '')
                    continue
                return r
                break
            except (ConnectionError, ValueError):
                if i > reattempt_count:
                    raise Exception('Unable to connect after 5 attempts')
                else:
                    i = i + 1
                    self.logger.info(
                        "Connection Error.Will re attempt after 5 seconds")
                    time.sleep(2)
     
    def create_targetNS_to_vservers_mapping(self):
        try:
            # Read data from file
            with open(self.selectedvservers, 'r') as file:
                data = json.load(file)

            # Update the keys in the dictionary
            migration = data['migration']
            for vserver in migration['vservers']:
                vserver['vserver_ipaddress'] = vserver.pop('ipaddress')
                vserver['vserver_name'] = vserver.pop('name')
                vserver['vserver_port'] = vserver.pop('port')
                vserver['vserver_protocol'] = vserver.pop('protocol')
                vserver['vserver_type'] = vserver.pop('type')
                if 'target_vservers' in vserver:
                    for target_vserver in vserver['target_vservers']:
                        target_vserver['vserver_ipaddress'] = target_vserver.pop('ipaddress')
                        target_vserver['vserver_name'] = target_vserver.pop('name')
                        target_vserver['vserver_port'] = target_vserver.pop('port')
                        target_vserver['vserver_protocol'] = target_vserver.pop('protocol')
                        target_vserver['vserver_type'] = target_vserver.pop('type')
            migration_obj = copy.deepcopy(migration)
            self.targetNS_to_vservers_mapping = migration_obj
        except Exception as e:
            self.logger.critical(f"Error in creating the NetScaler to VServer mapping. Check if VServer details are correctly specified in the {self.vservers} file and make sure the file is present in the location")
            raise e

    
    def get_cli_commands(self):
        try:
            config_commands = []
            fp = open(self.source)
            for cmd in fp:
                config_commands.append(cmd)
            fp.close()
            self.cli_commands = config_commands
            return self.cli_commands
        except Exception as e:
            self.logger.critical(f"Error in reading the commands from the given ns.conf - {self.source}. Check if the file is present at the given location and has read permission")
            self.error = str(e)
            return

    def create_extract_vservers_payload(self):
        try:
            self.logger.info("Creating Payload: Extract Vservers")
            payload = {}
            payload["adc_config"] = {}
            payload["adc_config"]["source"] = {}
            payload["adc_config"]["target"] = {}
            if sourceType == 'netscaler':
                payload["adc_config"]["source"]["instance_id"] = self.source_id
            else:
                payload["adc_config"]["source"]["cli_commands"] = self.cli_commands           
            payload["adc_config"]["target"]["instance_id"] = self.target_id
            return payload            
        except Exception as e:
            self.logger.critical("Error in creating the Extract VServer API payload")
            raise e

    def create_extract_vservers_config_payload(self, vservers_list):
        try:
            self.logger.info("Creating Payload: Extract Vservers Config")
            payload = {}
            payload["adc_config"] = {}
            payload["adc_config"]["source"] = {}
            payload["adc_config"]["target"] = {}
            if sourceType == 'netscaler':
                payload["adc_config"]["source"]["instance_id"] = self.source_id
            else:
                payload["adc_config"]["source"]["cli_commands"] = self.cli_commands          
            payload["adc_config"]["target"]["instance_id"] = self.target_id
            payload["adc_config"]["vservers"] = vservers_list
            payload["adc_config"]["skip_global_audit"] = True
            return payload            
        except Exception as e:
            self.logger.critical("Error in creating the Extract VServers Configuration API payload")
            raise e

    def create_migrate_vservers_config_payload(self, application_config, vservers, file_uploads, password_attributes):
        try:
            self.logger.info("Creating Payload: Migrate Vservers Config")
            payload = {}
            payload["adc_config"] = {}
            payload["adc_config"]["source"] = {}
            payload["adc_config"]["target"] = {}
            payload["adc_config"]["appname"] = ""
            payload["adc_config"]["is_manage_through_adm"] = False
            if sourceType == 'netscaler':
                payload["adc_config"]["source"]["instance_id"] = self.source_id
            payload["adc_config"]["source"]["cli_commands"] = application_config           
            payload["adc_config"]["target"]["instance_id"] = self.target_id
            payload["adc_config"]["vservers"] = vservers
            payload["adc_config"]["file_uploads"] = file_uploads
            payload["adc_config"]["password_attributes"] = password_attributes
            return payload            
        except Exception as e:
            self.logger.critical("Error in creating the Migrate Configuration API payload")
            raise e

    def save_extract_vservers_config_data(self, result):
        file_path = 'data/migrateconfig.json'
        data_to_store = {"migration": {}}

        try:
            # create the file
            if not os.path.exists(file_path):
                with open(file_path, 'w') as file:
                    json.dump(data_to_store, file, indent=4)
            else:
                with open(file_path, 'r') as file:
                    data_to_store = json.load(file)
        except Exception as e:
            self.logger.critical("Error in reading/updating the files and passwords details in data/migrateconfig.json")
            raise e
        data_to_store['migration'] = result
        try:
            # rewrite the updated data to the file
            with open(file_path, 'w') as file:
                json.dump(data_to_store, file, indent=4)
        except Exception as e:
            self.logger.critical("Error in reading/updating the files and passwords details in data/migrateconfig.json")
            raise e
        
    def print_files_and_password_details(self):
        try:
            # Load JSON data from file
            with open('data/migrateconfig.json') as file:
                json_data = json.load(file)
            # Print details
            self.print_details(json_data)
        except Exception as e:
            self.logger.critical("Error in reading from data/migrateconfig.json")

    def print_details(self, data):
        details = data['migration']
        if self.sourceType == 'file':
            if 'file_uploads' in details and details['file_uploads'] != []:
                print('\nFollowing are the files used by the selected set of VServers. Please copy all the required files under “data/files” directory\n')
                print(f"{'EntityType':<40}{'EntityName':<40}{'fileName':<40}")
                print("-" * 90)
                for upload in details.get("file_uploads", []):
                    print(f"{upload['resource_type']:<40}{upload['resource_name']:<40}{upload['filename']:<40}{'****' if 'password' in upload else ''}")
        if 'password_attributes' in details and details['password_attributes'] != []:
            print('\nFollowing are the password attributes used by the selected set of VServers.\nPlease edit data/migrateconfig.json file for ‘PASSWORD_NEEDED’ string and replace with the actual password values\n')
            print(f"{'EntityType':<40}{'EntityName':<40}{'password':<40}")
            print("-" * 90)
            for password_attr in details.get("password_attributes", []):
                print(f"{password_attr['resource_type']:<40}{password_attr['resource_name']:<40}{'****' if 'password' in password_attr else '***'}")
        print('\n')
            
    def remove_migration_data(self):
        file_path = 'data/migrateconfig.json'
        data_to_store = {"migration": {}}
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            if not os.path.exists(file_path):
                with open(file_path, 'w') as file:
                    json.dump(data_to_store, file, indent=4)
        except Exception as e:
            self.logger.critical("Error in removing the data/migrateconfig.json file")
            raise e
    def read_file_and_convert_to_json(self, file_path):
        try:
            with open(file_path, 'rb') as file:
                # Read the file content
                file_content = file.read()

                # Encode the content in base64
                base64_encoded_content = base64.b64encode(file_content).decode('utf-8')

                # Construct the JSON object
                filecontent = f"data:application/octet-stream;base64,{base64_encoded_content}"
                return filecontent
        except Exception as e:
            self.logger.error(f"Error in reading the content of the file to be uploaded ({file_path}): {e}")
            raise e

    def create_file_uploads_and_passwords_payload(self, target):
        try:
            files_payload = []
            passwords_payload = []
            application_config = []
            with open(self.passwords, 'r') as file:
                files_and_passwords = json.load(file)
            if bool(files_and_passwords):
                files_and_passwords = files_and_passwords['migration']
                if 'file_uploads' in files_and_passwords:
                    for file_upload in files_and_passwords['file_uploads']:
                        file_name = file_upload['filename']
                        filecontent = self.read_file_and_convert_to_json(os.path.dirname(self.passwords)+'/files/'+file_name)
                        file_upload['file_content'] = filecontent
                    files_payload = files_and_passwords['file_uploads']
                if 'password_attributes' in files_and_passwords:
                    passwords_payload = files_and_passwords['password_attributes']
                if 'application_config' in files_and_passwords:
                    application_config = files_and_passwords['application_config']
            return application_config, files_payload, passwords_payload
        except Exception as e:
            self.logger.critical(f"Error in creating the migrate config API payload. Check if the passwords are specified correctly in this file - {self.passwords}. Check if the file is available at the location.{str(e)}")
            raise e
    
    def write_to_vservers_file(self, vservers_response_data):
        try:
            data_to_store = {"migration": {
                "vservers": []
            }}
            # Update the keys in the dictionary
            for item in vservers_response_data:
                for key in list(item.keys()):
                    if key.startswith('vserver_'):
                        item[key[8:]] = item.pop(key)
                if 'target_vservers' in item:
                    for vserver in item['target_vservers']:
                        for key in list(vserver.keys()):
                            if key.startswith('vserver_'):
                                vserver[key[8:]] = vserver.pop(key)

            data_to_store['migration']['vservers'] = vservers_response_data

            if not os.path.exists('data'):
                os.makedirs('data')

            vserver_file_path = None
            if self.vservers is not None:
                vserver_file_path = self.vservers
            else:
                vserver_file_path = 'data/discovered_vservers.json'
            with open(vserver_file_path, 'w') as outfile:
                json.dump(data_to_store, outfile, indent=4)
            

            # create a copy of the file for user to update
            with open(self.selectedvservers, 'w') as outfile:
                json.dump(data_to_store, outfile, indent=4)

        except Exception as e:
            self.logger.critical(f"Error in writing the vserver details to file: {vserver_file_path}")
            raise e

    def print_info(self, stage_number):
        try:
            print('-----------------------------------------------------------------')

            if stage_number == 1:
                print('\nAll vserver details discovered on the NetScaler has been saved to data/discovered_vservers.json file.\n')
                print('A copy of this is created in the the path data/selected_vservers.json.\n')
                print('Update this file (data/selected_vservers.json) with the required vservers to proceed to extraction of vserver specific config.\n')
                print('Detailed next steps:\n')
                print('         1 - Edit the file data/selected_vservers.json to keep only entries for the vservers you want to migrate to the target NetScaler.\n')
                print('         2 - Rerun the same script and select the second option this time - extractvserversconfig\n')

            if stage_number == 2:
                print('Detailed next steps:\n')
                print('         1 - Review the file data/migrateconfig.json for the CLI configuration that will be migrated.\n')
                print('         2 - Rerun the same script and select the third option this time - migrateconfig\n')
                print('         3 - You will be asked this time to specify a target NetScaler for the migration.\n')

            print('-----------------------------------------------------------------')
        except Exception as e:
            self.logger.critical("Error in printing Stage details")
            raise e



    # def print_vserver_details(self, vserver, indent=0):
    #     indent_str = ' ' * indent
    #     print(f"{indent_str}Name:".ljust(20), vserver['name'])
    #     print(f"{indent_str}Type:".ljust(20), vserver['type'])
    #     print(f"{indent_str}IP Address:".ljust(20), vserver['ipaddress'])
    #     print(f"{indent_str}Port:".ljust(20), vserver['port'])
    #     print(f"{indent_str}Protocol:".ljust(20), vserver['protocol'])
    #     if 'target_vservers' in vserver and vserver['target_vservers'] != []:
    #         print(f"\n{indent_str}Target Virtual Servers:")
    #         for target_vserver in vserver['target_vservers']:
    #             self.print_vserver_details(target_vserver, indent + 4)

    def print_vservers(self, vservers, indent=0):
        for vserver in vservers:
            print("VServer:")
            for key, value in vserver.items():
                if isinstance(value, list):
                    print(f"{' ' * indent}{key}:")
                    self.print_vservers(value, indent + 2)
                else:
                    print(f"{' ' * indent}{key}: {value}")

    def parse_response(self, response):
        try:
            if response.ok:
                result = response.json()
                if 'errorcode' in result and result['errorcode'] != 0:
                    self.error = "Error in the API request. "
                    if 'message' in result:
                        self.error = self.error + result['message']
                    return None
                else:
                    # assuming success
                    return result
            else:
                try:
                    result = response.text if response.text else response.reason
                    print(response.json())
                    self.error = "Error in request processing. " + result
                except:
                    self.error = "Error in request processing. Reason UNKNOWN."

            return None
        except Exception as e:
            self.error = str(e)
            raise e

    def get_request_headers(self):
        
        sessionID = "SESSID="+self.sessionid
        headers = {
            'Content-type':'application/json',
            'Accept':'*/*',
            'Cookie':'{}'.format(sessionID),
            'Connection': 'keep-alive'
        }
        return headers

    def post_request(self, url, payload):
        try:
            headers = self.get_request_headers()
            response = requests.post(url, data=json.dumps(payload), headers=headers)
            return self.parse_response(response)
        except Exception as e:
            self.logger.critical(f"{url} - POST API request Failed")
            raise e

    def get_request(self, url):
        try:
            headers = self.get_request_headers()
            response = requests.get(url, headers=headers)
            return self.parse_response(response)
        except Exception as e:
            self.logger.critical(f"{url} - GET API request Failed")
            return None

    def delete_request(self, url):
        try:
            headers = self.get_request_headers()
            response = requests.delete(url, headers=headers)
            return self.parse_response(response)
        except Exception as e:
            self.logger.critical(f"{url} - DELETE API request Failed")
            return None

    def get_job_status(self, job_id, operation):
        try:
            self.logger.info("Fetching the job status")
            if self.adm_type == 'service':
                request_url = 'https://' + self.adm_svc_url + self.basepath + '/jobs/' + job_id
            else:
                request_url = self.protocol + '://' + self.adm_ip +  self.basepath + '/jobs/' + job_id
            #sometimes, JOB-ID is created with a little delay.. so introducing sleep
            time.sleep(5)
            last_progress = {}
            while True:
                result = self.get_request(request_url)
                if self.error:
                    self.logger.critical(self.error)
                    return None

                if result and 'errorcode' in result and result['errorcode'] != 0:
                    self.error = result['message']
                    self.logger.critical(self.error)
                    return None

                if not 'job' in result or not 'progress_info' in result['job'] or len(result['job']['progress_info']) == 0:
                    # progress is not yet returned
                    time.sleep(1)
                    continue
                print(".", end=" ", flush=True)
                last_progress = result['job']['progress_info'][len(result['job']['progress_info'])-1]
                if 'is_last' in last_progress and last_progress['is_last'] == "true":
                    break
                time.sleep(1)
            print('\n')
            status = result['job']['status']
            if status.lower() in ['failed']:
                # failed to process the request
                #print all the failed progress 
                index = 1
                while True:
                    if len(result['job']['progress_info'])-index < 0:
                        break
                    progress = result['job']['progress_info'][len(result['job']['progress_info'])-index]
                    index = index + 1
                    if 'status' in progress and progress['status'] == "failed":
                        self.logger.critical(progress['message'])
                    else:
                        break
                self.error = last_progress['reason']
                self.logger.critical(self.error)
                return None
            elif status.lower() in ['completed', 'success']:
                result_obj = result['job']['result'].get('adc_config', {})
                if operation == 'extract_vservers_config':
                    if 'vis_configs' in result_obj:
                        result_obj.pop('vis_configs')
                    if 'auth_configs' in result_obj:
                        result_obj.pop('auth_configs')
                    if 'global_policy_bindpoints_config' in result_obj:
                        result_obj.pop('global_policy_bindpoints_config')
                    if 'ip_port_configs' in result_obj:
                        result_obj.pop('ip_port_configs')
                    if 'stylebook_info' in result_obj:
                        result_obj.pop('stylebook_info')
                    if 'unsupported_config' in result_obj:
                        result_obj.pop('unsupported_config')
                    if 'global_config' in result_obj:
                        result_obj.pop('global_config')
                return result_obj

            self.error = last_progress['message']
            self.logger.critical(self.error)
            return None
        except Exception as e:
            self.error = "Error in fetching job status: " + str(e)
            self.logger.critical(self.error)
            return None
    
    def print_time_taken(self, operation, start_time, end_time):
        time_taken = end_time - start_time
        hours, remainder = divmod(time_taken, 3600)
        minutes, seconds = divmod(remainder, 60)
        time_str = f'Time taken by {operation} operation: '
        if int(hours) > 0:
            time_str += f'{int(hours)}h '
        if int(minutes) > 0:
            time_str += f'{int(minutes)}m '
        time_str += f'{int(seconds)}s'
        self.logger.info(time_str)

    def extract_vservers(self, request_payload):
        try:
            self.error = None
            start_time = time.time()
            self.logger.info("Extracting the Virtual Servers")

            if self.adm_type == 'service':
                request_url = 'https://' + self.adm_svc_url + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_service_header(self.sessionid, 'true')
            else:
                request_url = self.protocol + '://' + self.adm_ip + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_onprem_header(self.sessionid, '')
            result = requests.post(request_url, json=request_payload, headers=headers)
            if self.error:
                self.logger.critical(self.error)
                return None

            if result and 'errorcode' in result and result['errorcode'] != 0:
                self.error = result['message']
                self.logger.critical(self.error)
                return None
            job_id = result.json()['job']['job_id']
            result = self.get_job_status(job_id, self.operation)
            end_time = time.time()
            self.print_time_taken('extract_vservers', start_time, end_time)
            return result
        except Exception as e:
            self.error = "Error in extracting vservers"
            self.logger.critical(self.error)
            return None

    def extract_vservers_config(self, request_payload, vserver_names):
        try:
            self.error = None
            start_time = time.time()
            self.logger.info(f"Extracting the Application Configuration for these VServers - {vserver_names}")

            if self.adm_type == 'service':
                request_url = 'https://' + self.adm_svc_url + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_service_header(self.sessionid, 'true')
            else:
                request_url = self.protocol + '://' + self.adm_ip + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_onprem_header(self.sessionid, '')
            result = requests.post(request_url, json=request_payload, headers=headers)

            if self.error:
                self.logger.critical(self.error)
                return None

            if result and 'errorcode' in result and result['errorcode'] != 0:
                self.error = result['message']
                self.logger.critical(self.error)
                return None

            job_id = result.json()['job']['job_id']
            result = self.get_job_status(job_id, self.operation)
            end_time = time.time()
            self.print_time_taken(self.operation, start_time, end_time)
            return result
        except Exception as e:
            self.error = "Error in extracting VServer specific configuration"
            self.logger.critical(self.error)
            raise e

    def migrate_vservers_config(self, request_payload):
        try:
            time.sleep(10)
            self.error = None
            start_time = time.time()
            self.logger.info("Migrating the Virtual Servers Config")

            if self.adm_type == 'service':
                request_url = 'https://' + self.adm_svc_url + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_service_header(self.sessionid, 'true')
            else:
                request_url = self.protocol + '://' + self.adm_ip + self.basepath + self.endpoint + '/' + self.operation
                headers = self.get_onprem_header(self.sessionid, '')
            
            result = requests.post(request_url, json=request_payload, headers=headers)
            
            if self.error:
                self.logger.critical(self.error)
                return None

            if result and 'errorcode' in result and result['errorcode'] != 0:
                self.error = result['message']
                self.logger.critical(self.error)
                return None
            job_id = result.json()['job']['job_id']
            self.configpackid = job_id
            job_id = result.json()['job']['job_id']
            result = self.get_job_status(job_id, self.operation)
            end_time = time.time()
            self.print_time_taken(self.operation, start_time, end_time)
            return result
        except Exception as e:
            self.error = "Error in migrating the VServers to Target NetScaler"
            self.logger.critical(self.error)
            raise e
    
    def logout_from_adm_svc(self):
        try:
            self.logger.info('Logging out from ADM.')
            url = 'https://'+self.adm_svc_url+'/nitro/v1/config/login'
            method = 'DELETE'
            headers = {'Content-Type': 'application/json', 'Cookie': 'SESSID='+self.sessionid}
            response = self.send_curl_request(url, method, None, headers)
            if response.status_code == 200 and response.json()['username'] != "" and response.json()['tenant_id'] != "" and response.json()['tenant_name'] == self.tenant_name:
                self.logger.info(f"Logout from ADM ({self.adm_svc_url}) successful.")
            else:
                self.logger.critical("Logout failed. Status code:", response.status_code)
        except Exception as e:
            self.error = "Error in logging out from ADM: " + str(e)
            self.logger.critical(self.error)
            return None
        
    def logout_from_adm_onprem(self):
        try:
            self.logger.info('Logging out from ADM.')
            url = 'http://'+self.adm_ip+'/nitro/v1/config/login'
            method = 'DELETE'
            headers = {'Content-Type': 'application/json', 'Cookie': 'SESSID='+self.sessionid}

            # Send the request
            response = self.send_curl_request(url, method, None, headers)

            # Check the response
            if response.status_code == 200 and response.json()['username'] == adm_username and response.json()['tenant_id'] != "":
                self.logger.info(f"Logout from ADM ({self.adm_ip}) successful.")
            else:
                self.logger.critical("Logout failed. Status code:", response.status_code)
        except Exception as e:
            self.error = "Error in logging out from ADM: " + str(e)
            self.logger.critical(self.error)
            return None

    def logout_from_adm(self):
        try:
            if self.adm_type == 'service':
                self.logout_from_adm_svc()
            else:
                self.logout_from_adm_onprem()
        except Exception as e:
            raise e

    def login_to_adm_service(self):

        try:
            api_url = "https://%s/nitro/v2/config/login" % self.adm_svc_url
            login_request = {"login": {"ID": self.adm_svc_client_id, "Secret":  self.adm_svc_client_secret }}

            response = self.send_curl_request(api_url, 'POST', json.dumps(login_request))
            # response = requests.post(api_url, json=login_request, verify=False)

            # Check the response
            if response.status_code == 200:
                self.logger.info(f"Login to ADM ({self.adm_svc_url}) successful.")
                # Extract session ID from cookies if present
                response_payload = response.json()
                session_id = response_payload["login"][0]["sessionid"]
                if session_id:
                    self.sessionid = session_id   
                    self.tenant_name = response_payload["login"][0]["tenant_name"]
                    return session_id
                else:
                    self.logger.info("Session ID not found in response cookies.")
            else:
                self.logger.critical("Login failed. Status code:", response.status_code)
        except Exception as e:
            self.error = "Error in logging in to ADM Svc. Check the ADM URL, Client ID and Client secret. Make sure the ADM is reachable."
            self.logger.critical(self.error)
            raise e

    def login_to_adm_onprem(self):
        try:
            url = 'http://'+self.adm_ip+'/nitro/v1/config/login'
            method = 'POST'
            data = {"login": {"username": self.adm_username, "password": self.adm_password}}
            headers = {'Content-Type': 'application/json'}
            # Convert data to JSON format and add "object=" prefix
            payload = "object=" + json.dumps(data)

            # Send the request
            response = self.send_curl_request(url, method, payload, headers)

            # Check the response
            if response.status_code == 200:
                self.logger.info(f"Login to ADM ({self.adm_ip}) successful.")
                # Extract session ID from cookies if present
                session_id = self.get_session_id(response.cookies)
                if session_id:
                    self.sessionid = session_id
                    return session_id
                else:
                    self.logger.info("Session ID not found in response cookies.")
            else:
                self.logger.critical("Login failed. Status code:", response.status_code)
        except Exception as e:
            self.error = "Error in logging in to ADM On-prem. Check the ADM IP, username and password. Make sure the ADM is reachable."
            self.logger.critical(self.error)
            raise e
    
    def login_to_adm(self):
        try:
            self.logger.info('Logging in to ADM')
            if self.adm_type == 'service':
                self.login_to_adm_service()
            else:
                self.login_to_adm_onprem()
        except Exception as e:
            self.error = "Error in logging in to ADM"
            self.logger.critical(self.error)
            raise e

    def get_session_id(self, cookies):
        for cookie in cookies:
            if cookie.name == 'SESSID':
                return cookie.value
        return None

    def send_curl_request(self, url, method='GET', data=None, headers=None):
        if method.upper() == 'GET':
            response = requests.get(url, params=data, headers=headers)
        elif method.upper() == 'POST':
            # For POST requests, the data parameter is used to send the payload
            response = requests.post(url, data=data, headers=headers)
        elif method.upper() == 'PUT':
            response = requests.put(url, data=data, headers=headers)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, data=data, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return response
    
def is_ip_or_path(source):
    # Check if source is a valid file path
    if os.path.isfile(source):
        return 'file'
    # Check if source is a valid IP address
    try:
        ipaddress.ip_address(source)
        return 'netscaler'
    except ValueError:
        return 'invalid'

def arg_parse(argv):
    source = None
    adm_type = ''
    adm_ip = ''
    adm_username = ''
    adm_password = ''
    adm_svc_url = ''
    adm_svc_client_id = ''
    adm_svc_client_secret = ''
    target = ''

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-source',
        '--source',
        help="Provide the input NS.CONF file path or source NetScaler IP address",
        default='', 
        required=True)
    parser.add_argument(
        '-adm',
        '--adm',
        help="Provide ADM IP address", 
        required=True)
    parser.add_argument(
        '-target',
        '--target',
        help="IPAddress of the NetScaler that is being managed by ADM. This is required by the migration workflow to parse the input configuration file.")
    parser.add_argument(
        '-extractvservers', 
        action='store_true', 
        help='Specify to extract vservers')
    parser.add_argument(
        '-extractvserversconfig', 
        action='store_true', 
        help='Specify to extract the vserver specific config')
    parser.add_argument(
        '-migrateconfig', 
        action='store_true', 
        help='Specify to migrate the vservers')
    
    args = parser.parse_args(argv)

    if args.source:
        source = args.source
    if args.target:
        target = args.target

    adm_type = os.getenv('ADM_TYPE')
    if not adm_type:
        print("Expect to find an environment variable called ADM_TYPE with the ADM type (onprem or service)")
        sys.exit(1)

    if adm_type == 'onprem':
        if args.adm:
            adm_ip = args.adm
        adm_username = os.getenv('ADM_USERNAME')
        if not adm_username:
            print("Expect to find an environment variable called ADM_USERNAME with the ADM username")
            sys.exit(1)

        adm_password = os.getenv('ADM_PASSWORD')
        if not adm_password:
            print("Expect to find an environment variable called ADM_PASSWORD with the ADM password")
            sys.exit(1)
    else:
        if args.adm:
            adm_svc_url = args.adm
        adm_svc_client_id = os.getenv('ADM_SVC_CLIENT_ID')
        if not adm_svc_client_id:
            print("Expect to find an environment variable called ADM_SVC_CLIENT_ID with the ADM Service Client ID")
            sys.exit(1)

        adm_svc_client_secret = os.getenv('ADM_SVC_CLIENT_SECRET')
        if not adm_svc_client_secret:
            print("Expect to find an environment variable called ADM_SVC_CLIENT_SECRET with the ADM Service Client Secret")
            sys.exit(1)


    operation = ''
    if args.extractvservers:
        operation = 'extract_vservers'
    if args.extractvserversconfig:
        operation = 'extract_vservers_config'
    if args.migrateconfig:
        operation = 'migrate_vservers_config'
    

    sourceType = is_ip_or_path(source)

    # source should be a valid file path or a valid NetScaler IP address
    if sourceType == 'invalid':
        print('Invalid source provided. Please provide a valid file path or NetScaler IP address')
        sys.exit(1)
    if not source:
        print('Please provide input ns.conf file path or source NetScaler IP address')
        sys.exit(1)
    # target netscaler is required at all steps if source is a file
    if sourceType == 'file' and target == '':
        print('Please provide Target NetScaler IP address')
        sys.exit(1)
    # target netscaler is required at the final step of migration if source is a netscaler
    if sourceType == 'netscaler' and operation == 'migrate_vservers_config' and target == '':
        print('Please provide Target NetScaler IP address')
        sys.exit(1)
    if adm_ip == '' and adm_svc_url == '':
        if adm_ip == '':
            print('Please provide ADM Server IP')
        elif adm_svc_url == '':
            print('Please provide ADM Service URL')
        sys.exit(1)

    if operation == '':
        print('Please provide one of the task (extractvservers, extractvserversconfig, migrateconfig)')
        sys.exit(1)
    
    return source, adm_type, adm_ip, adm_username, adm_password, adm_svc_url, adm_svc_client_id, adm_svc_client_secret, target, operation, sourceType

if __name__ == "__main__":
    source, adm_type, adm_ip, adm_username, adm_password, adm_svc_url, adm_svc_client_id, adm_svc_client_secret, target, operation, sourceType = arg_parse(sys.argv[1:])
    migrate = migration(source, adm_type, adm_ip, adm_username, adm_password, adm_svc_url, adm_svc_client_id, adm_svc_client_secret, operation, sourceType, target)
    migrate.perform_operation()
    print("To check success or failure of the operation, please check the last log file in the log directory")