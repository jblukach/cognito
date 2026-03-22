# cognito

This project provides a **multi-region** authentication architecture using **Amazon Cognito** with managed login pages and region-specific endpoints.

Two independent **User Pools** are deployed to provide regional authentication redundancy:

- **us-east-1**
- **us-west-2**

Each region hosts its own login flow that ultimately generates a **Bearer** token used to access the **API Gateway** by **Lambda Authorizer**.

------------------------------------------------------------------------

# Login Flow

**User**\
↓\
**Root** -> api.lukach.io\
↓\
**Login** -> hello-use1.lukach.io or hello-usw2.lukach.io\
↓\
**Auth** -> use1.api.lukach.io/auth or usw2.api.lukach.io/auth\
↓\
**Home** -> use1.api.lukach.io/home or usw2.api.lukach.io/home

------------------------------------------------------------------------
