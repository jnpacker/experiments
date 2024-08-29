
# How to install the community edition of ACM
## Quickstart
1. Log into an OpenShift cluster, Minimum size is Single node OpenShift m5.2xlarge (AWS)
2. Apply the operator.yaml
```
  oc apply -f ./operator/install-community-0.5.yaml
```
3. Check the Stolostron CSV from the cli, or use the OpenShift console `Operators` > `Installed Operators`
```
  oc -n open-cluster-management get csv stolostron.v0.5.0  # Where v0.5.0 is the community-VERSION you chose X.Y.Z

  # Look for the `status` > `Conditions` > `Phase`
  #
  Message: waiting for install components to report healthy
  Phase: Installing
  Reason: InstallSucceeded
```
4. Create the Multi-Cluster Hub custom resource, this can be done in the console at the `Details` section, but pressing the button to create the `Multi-Cluster Hub` custom resource. Leave the defaults and `save` it, about 5min's later ACM should be installed
```
  # CLI command
  oc apply -f multiclusterhub.yaml -o yaml
```

6. Monitor multiclusterengine status
   * Check `Stolostron-Engine` first, navigate to the multiclusterengine and validate the event `All components deployed`
    ```
    # From the cli
    oc get multiclusterengine multiclusterengine
    # At the very bottom look for
    #
    phase: Available
    ```
7. Monitor multiclusterhub status
    * Check `Stolostron` second, navigate to the multiclusterhub and validate the event `All components deployed`
    ```
    # From the cli
    oc get open-cluster-management multiclusterhub
    # At the very bottom look for
    #
    phase: Available
    ```
