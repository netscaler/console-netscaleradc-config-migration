# Pre-requisite
    NetScaler Console (formerly known as ADM)
    Target NetScaler (managed by Console)
    Client machine with shell terminal, access to NetScaler Console
    
# Introduction to NetScaler Configuration Migration Script
This repository contains a user-interactive shell script designed to facilitate the migration of NetScaler's application configurations in Application Delivery Management (ADM) systems. The script is compatible with both on-premises NetScaler Console and NetScaler Console Service. It makes use of NetScaler Console APIs for migrating application condifurations from either a source ns.conf or a source NetScaler (managed by Console) to another target NetScaler.

# Usage
To execute the script, run the following command in your terminal:
./config_migrate.sh

The script will guide you through the following steps:

    1. Setup Type Selection: Choose between 'ADM On-Prem' or 'ADM Service'.
    2. Credentials Input: Depending on your previous choice, you will be asked to provide:
            * For 'ADM On-Prem': ADM IP address, username, and password.
            * For 'ADM Service': ADM Service URL, Client ID, and Client Secret.
    3. Source Specification: Provide the NetScaler IP address or the path to the NS.CONF file.
    4. Operation Selection: Choose an operation to perform:
            * Discover all Vservers in the configuration
            * Extract the configuration of the selected vservers
            * Migrate the selected vservers configuration to the target NetScaler
    5. Target Specification: If the source is a file or if the operation is 'migrateconfig', provide the Target NetScaler IP address.

# Post-Execution Steps

# After the Extract VServers Step,
    All vserver details discovered on the NetScaler are saved to the data/discovered_vservers.json file. A copy of this file is created at data/selected_vservers.json. To proceed with the extraction of vserver-specific config, perform the following steps:

        1. Edit the data/selected_vservers.json file to retain only the entries for the vservers you wish to migrate to the target NetScaler.
        2. Rerun the script and select the 'extractvserversconfig' option.

# After the Extract VServers Config Step, 
    The configuration files like certificates/keys/htmlerrorpages/appfwsignatures used by the selected set of VServers are listed. Copy all the required files under the data/files directory. Also, the password attributes used by the selected set of VServers are displayed. Replace the PASSWORD_NEEDED string in the data/migrateconfig.json file with the actual password values.
    Note, if the source is also a NetScaler, then the required configuration files are automatically copied from source to target NetScaler during the Migrate operation. However, User still need to provide passwords in the data/migrateconfig.json file if any.

    To proceed with the migration, perform the following steps:
        1. Review the data/migrateconfig.json file for the CLI configuration that will be migrated.
        2. Rerun the script and select the 'migrateconfig' option.
        3. Specify a target NetScaler for the migration when prompted.

# After the Migrate Config Step, 
    Upon successful completion of the 'Migrate Config' step, the specified configuration is seamlessly applied to the target NetScaler.
