# Raw material

From Joe.

## For Multicluster Hub 

Informally, for either OperatorHub UI or CLI install, just make the following substitutions:
For ACM:

Use package name stolostron rather than advanced-cluster-management
Use catalog source community-operators rather than redhat-operatos
Use channel community-0.5 rather than what will eventually be released as release-2.12.

Installing stolostron will use stolostron-engine for its "MCE".   Once the operator is installed, follow normal ACM instructions for creating the hub operand, eg. create a MulticlusterHub resource.  (CRD names and API groups are exactly the same as productized deliverable.)

## For Multicluster Engine Standalone:

Use package name stolostron-engine rather than multiclsuter-engine
Use catalog source community-operators rather than redhat-operatos
Use channel community-0.5 rather than what will eventually be released as stable-2.7.
Once the operator is installed, follow standard MCE procedures for creating the operand "engine", i.e. create a MulticlusterEngine resource.
Note that for the community operators, upgrade from a previous release is not supported or tested. (edited)