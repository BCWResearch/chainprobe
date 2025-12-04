
# Ansible Playbook Execution Guide

This document outlines how to execute the main Ansible automation script using the Latitude infrastructure inventory.

## 1\. The Command

To run the deployment on the target servers, execute the following command from the root of the project directory:

```bash
ansible-playbook -i latitude.ini run.yaml
```

## 2\. Command Breakdown

| Component | Description |
| :--- | :--- |
| **`ansible-playbook`** | The standard Ansible command-line tool used to run automation scripts. |
| **`-i latitude.ini`** | **Inventory Flag:** Specifies the inventory file to use. <br>• `latitude.ini` contains the list of server IP addresses (e.g., `109.94.96.101`) and connection details (SSH users, keys). |
| **`run.yaml`** | **Playbook File:** The entry point for the automation logic. <br>• This file defines the *tasks* to be executed (e.g., pulling code from Git, restarting services). |

## 3\. Prerequisites

Before running this command, ensure:

1.  **Ansible is installed** on your local machine (`ansible --version`).
2.  **SSH Access:** You have SSH access to the servers listed in `latitude.ini`.
3.  **Directory:** You are inside the directory containing both `latitude.ini` and `run.yaml`.

## 4\. Useful Command Variations

### A. Verbose Mode (For Debugging)

If the playbook fails or hangs (e.g., on a Git task), use verbose mode to see detailed SSH logs and error messages:

```bash
ansible-playbook -i latitude.ini run.yaml -vvv
```

### B. Dry Run (Check Mode)

To simulate the playbook without making actual changes to the server:

```bash
ansible-playbook -i latitude.ini run.yaml --check
```

### C. Limit to Specific Host

If `latitude.ini` contains many servers but you only want to update one:

```bash
ansible-playbook -i latitude.ini run.yaml --limit 109.94.96.101
```
