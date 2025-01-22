# Activating CNV
* Goto `OperatorHub`, search for `cnv`
* Choose OpenShift Virtualization
* Leave the default `Channel` and `Version`, and press `Install`
* On the `Install Operator` page, leave the default and press `Install`
* Add a `value: 'true'` for the `env:` key `- name: KVM_EMULATION` to the CSV operator yaml
* Create the HyperConverged CR
* Set the local storage class value if you have one (if not, create only ephemeral VM's)
* View the YAML for the OpenShift Virtualization operator
# Creating VM's
* Apply the `fedora-ephemeral.yaml` or `fedora-persistent.yaml` virtual machines
