#!/bin/bash

# Initialize a boolean variable for the IP validity
is_valid_source_ip=false
is_valid_file=false
is_valid_adm_ip=false

echo "Select the setup type:"
echo "1. ADM On-Prem"
echo "2. ADM Service"

while true; do
    # Read user input
    read -p "Enter your choice (1-2): " adm_type

    # Validate user input
    case $adm_type in
        1)
            adm_type="onprem"
            break
            ;;
        2)
            adm_type="service"
            break
            ;;
        *)
            echo "Invalid choice. Please enter a number from 1 to 2."
            ;;
    esac
done

if [ "$adm_type" == "onprem" ]; then
    echo "You have selected ADM On-Prem setup"
    # get adm IP
    echo -n "Provide the ADM IP address: "
    read adm_ip

    # Check if the ADM IP is a valid IP
    if [[ $adm_ip =~ ^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$ ]]; then
        is_valid_adm_ip=true
    else
        echo "Invalid ADM IP. ADM IP should be a valid IP address"
        exit 1
    fi

    # get adm username
    echo -n "Provide the ADM username: "
    read adm_username

    # get adm password
    echo -n "Provide the ADM password: "
    read -s adm_password

    adm="$adm_ip"
else
    # get adm svc URL
    echo -n "Provide the ADM Service URL: "
    read adm_svc_url

    # get adm svc client ID
    echo -n "Provide the ADM Service Client ID: "
    read adm_svc_client_id

    # get adm svc client secret
    echo -n "Provide the ADM Service Client Secret: "
    read -s adm_svc_client_secret

    echo "You have selected ADM Service setup"

    adm="$adm_svc_url"
fi


echo
# get source
echo -n "Provide the NetScaler IP address OR the NS.CONF file path: "
read source

# check if the source is a valid IP or a valid file path
if [[ $source =~ ^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$ ]]; then
    is_valid_source_ip=true
elif [[ -f $source ]]; then
    is_valid_file=true
else
    echo "Invalid source. Source should be a valid file path or a valid NetScaler IP address"
    exit 1
fi


# Display menu options
echo "Select the operation to perform:"
echo "1. Discover All Vservers in the configuration"
echo "2. Extract the configuration of the selected vservers"
echo "3. Migrate the selected vservers configuration to the target NetScaler"

while true; do
    # Read user input
    read -p "Enter your choice (1-3): " operation

    # Validate user input
    case $operation in
        1)
            operation_name="extractvservers"
            break
            ;;
        2)
            operation_name="extractvserversconfig"
            break
            ;;
        3)
            operation_name="migrateconfig"
            break
            ;;
        *)
            echo "Invalid choice. Please enter a number from 1 to 3."
            ;;
    esac
done


# Ask for the target NetScaler IP if the source is a file or if the operation is migrateconfig
if $is_valid_file || [ "$operation_name" == "migrateconfig" ]; then
    echo -n "Provide the Target NetScaler IP address: "
    read target
fi

# Prevent these commands from being echoed to the terminal"
set +x
export ADM_USERNAME="$adm_username"
export ADM_PASSWORD="$adm_password"

export ADM_SVC_CLIENT_ID="$adm_svc_client_id"
export ADM_SVC_CLIENT_SECRET="$adm_svc_client_secret"
set -x

export ADM_TYPE="$adm_type"

# Combine the ADM parameters

# Run the Python script with the parameters
if [[ -n $target ]]; then
    /usr/bin/env python3 config_migrate.py -adm "$adm" -source "$source" -target "$target" "-$operation_name"
else
    /usr/bin/env python3 config_migrate.py -adm "$adm" -source "$source" "-$operation_name"
fi