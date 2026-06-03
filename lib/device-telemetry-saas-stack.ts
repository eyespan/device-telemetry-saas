import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as waf from 'aws-cdk-lib/aws-wafv2';
import * as cw from 'aws-cdk-lib/aws-cloudwatch';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as timestream from 'aws-cdk-lib/aws-timestream';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as elbv2targets from 'aws-cdk-lib/aws-elasticloadbalancingv2-targets';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';


export class DeviceTelemetrySaasStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ====================== NETWORKING ======================
    const vpc = new ec2.Vpc(this, 'AppVpc', {
      maxAzs: 2,
      natGateways: 1, // ← was 1, ~$32/month saved
      subnetConfiguration: [
        {
          name: 'isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
        {
            name: 'public',
            subnetType: ec2.SubnetType.PUBLIC,
            cidrMask: 24,
          },
          {
            name: 'private',
            subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
            cidrMask: 24,
          },
      ],
    });

    // ====================== VPC ENDPOINTS ======================
// Removes NAT Gateway dependency for AWS service calls

  // DynamoDB — Gateway endpoint (free)
    vpc.addGatewayEndpoint('DynamoEndpoint', {
  service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
    });

  // S3 — Gateway endpoint (free)
    vpc.addGatewayEndpoint('S3Endpoint', {
  service: ec2.GatewayVpcEndpointAwsService.S3,
    });

  // SQS — Interface endpoint (small hourly cost, but much cheaper than NAT)
    vpc.addInterfaceEndpoint('SqsEndpoint', {
        service: ec2.InterfaceVpcEndpointAwsService.SQS,
        privateDnsEnabled: true,
    });

  // Timestream — Interface endpoint
    vpc.addInterfaceEndpoint('TimestreamEndpoint', {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${this.region}.timestream.ingest-cell2`,
        443
      ),
      privateDnsEnabled: false, // Timestream uses cell-based endpoints, private DNS not supported
    });

    const timestreamQueryEndpoint = vpc.addInterfaceEndpoint('TimestreamQueryEndpoint', {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${this.region}.timestream.query-cell2`, 
        443
      ),
      privateDnsEnabled: false, // cell-based endpoints don't support private DNS
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
    });

  // CloudWatch Logs — Interface endpoint (needed for Lambda logging)
    vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
  privateDnsEnabled: true,
     });

    // ====================== DATA STORES ======================
    // DynamoDB
    const telemetryTable = new dynamodb.Table(this, 'TelemetryTable', {
      partitionKey: { name: 'deviceId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
    });

    // Timestream
    const timestreamDb = new timestream.CfnDatabase(this, 'TimestreamDb', { 
      databaseName: 'telemetry_ts' 
    });



    const timestreamTable = new timestream.CfnTable(this, 'TimestreamTable', {
      databaseName: timestreamDb.databaseName!,
      tableName: 'metrics',
      retentionProperties: {
        memoryStoreRetentionPeriodInHours: '24',
        magneticStoreRetentionPeriodInDays: '7',
      },
    });
    timestreamTable.node.addDependency(timestreamDb);

    // S3 + CloudFront
    const assetBucket = new s3.Bucket(this, 'AssetBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const distribution = new cloudfront.Distribution(this, 'Cdn', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(assetBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
    });

    // ====================== QUEUE ======================
    const processingQueue = new sqs.Queue(this, 'ProcessingQueue', {
      visibilityTimeout: cdk.Duration.seconds(300),
      encryption: sqs.QueueEncryption.KMS_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ====================== IAM ROLE ======================
    const lambdaRole = new iam.Role(this, 'LambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
      ],
    });

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'dynamodb:PutItem', 'dynamodb:GetItem', 'dynamodb:Query',
        'sqs:SendMessage',
        'timestream:WriteRecords',
        'timestream:DescribeEndpoints',  // ← add this
        'logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents',
      ],
      resources: [
        telemetryTable.tableArn,
        `${telemetryTable.tableArn}/index/*`,
        processingQueue.queueArn,
        '*', // Timestream DescribeEndpoints doesn't support resource-level restriction
      ],
    }));

    // ====================== LAMBDAS ======================
    const apiLambda = new lambda.Function(this, 'ApiHandler', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/api'),
      role: lambdaRole,
      timeout: cdk.Duration.seconds(120),
      //memorySize: 512,
      //reservedConcurrentExecutions: 20, // ← cap concurrent executions
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      environment: {
        TABLE_NAME: telemetryTable.tableName,
        QUEUE_URL: processingQueue.queueUrl,
        NODE_ENV: 'production',
      },
    });

    const sqsLambda = new lambda.Function(this, 'SqsProcessor', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/processor'),
      role: lambdaRole,
      timeout: cdk.Duration.seconds(60),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      environment: {
        TABLE_NAME: telemetryTable.tableName,  // ← add this
        TIMESTREAM_DB: 'telemetry_ts',        // ← add
        TIMESTREAM_TABLE: 'metrics',          // ← add
        TIMESTREAM_ENDPOINT: `vpce-07974d711b4ebcb64-o05cj6z4.ingest-cell2.timestream.us-east-1.vpce.amazonaws.com`, // ← add
        NODE_ENV: 'production',
      },
    });

    sqsLambda.addEventSource(new lambdaEventSources.SqsEventSource(processingQueue));

    // ====================== API GATEWAY CLOUDWATCH ROLE ======================
  const apiGatewayLoggingRole = new iam.Role(this, 'ApiGatewayLoggingRole', {
   assumedBy: new iam.ServicePrincipal('apigateway.amazonaws.com'),
    managedPolicies: [
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonAPIGatewayPushToCloudWatchLogs'),
    ] ,
  });

// Set the role ARN in API Gateway account settings
  new apigw.CfnAccount(this, 'ApiGatewayAccount', {
      cloudWatchRoleArn: apiGatewayLoggingRole.roleArn,
  });

    // ====================== API GATEWAY ======================
    const api = new apigw.LambdaRestApi(this, 'TelemetryApi', {
      handler: apiLambda,
      proxy: false,
      deployOptions: {
        stageName: 'prod',
        metricsEnabled: true,
        loggingLevel: apigw.MethodLoggingLevel.INFO,
        throttlingRateLimit: 100,
        throttlingBurstLimit: 200,
        methodOptions: {
          '/devices/POST': { throttlingRateLimit: 50, throttlingBurstLimit: 100 },
          '/devices/GET':  { throttlingRateLimit: 100, throttlingBurstLimit: 150 },
        },
      },
    });

    // Usage plan — defines throttle + quota tiers
    const usagePlan = new apigw.UsagePlan(this, 'TelemetryUsagePlan', {
  name: 'TelemetryStandardPlan',
  description: 'Standard tier for telemetry API',
  throttle: {
    rateLimit: 50,
    burstLimit: 100,
  },
  quota: {
    limit: 10000,          // max 10k requests per day
    period: apigw.Period.DAY,
  },
  apiStages: [{
    api,
    stage: api.deploymentStage,
  }],
    });

  // API key for non-Cognito clients or additional tracking
    const apiKey = new apigw.ApiKey(this, 'TelemetryApiKey', {
    apiKeyName: 'telemetry-default-key',
    description: 'Default API key for telemetry clients',
    enabled: true,
    });

    usagePlan.addApiKey(apiKey);


  // ── Outputs ───────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiKeyId', {
      value: apiKey.keyId,
      description: 'API Key ID — retrieve value with: aws apigateway get-api-key --api-key <id> --include-value',
    });

     api.node.addDependency(apiGatewayLoggingRole);
    
     const devices = api.root.addResource('devices');

     

    //devices.addMethod('POST', new apigw.LambdaIntegration(apiLambda));
    //devices.addMethod('GET', new apigw.LambdaIntegration(apiLambda));

    // ====================== WAF ======================
    const webAcl = new waf.CfnWebACL(this, 'ApiWaf', {
      defaultAction: { allow: {} },
      scope: 'REGIONAL',
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: 'TelemetryWaf'
      },
      rules: [
        {
          name: 'AWSManagedRulesCommonRuleSet',
          priority: 1,
          statement: {
            managedRuleGroupStatement: { vendorName: 'AWS', name: 'AWSManagedRulesCommonRuleSet' }
          },
          overrideAction: { none: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'CommonRuleSet'
          },
        },
        // ── Add this rate limit rule ──────────────────────
        {
          name: 'RateLimitRule',
          priority: 2,
          statement: {
            rateBasedStatement: {
              limit: 300,           // max 300 requests per 5 min per IP
              aggregateKeyType: 'IP',
            },
          },
          action: { block: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'RateLimit',
          },
        },
      ],
    });

    // Associate WAF with API Gateway stage
    new waf.CfnWebACLAssociation(this, 'WafAssoc', {
      resourceArn: api.deploymentStage.stageArn,
      webAclArn: webAcl.attrArn,
    });

    // ====================== MONITORING ======================
    new cw.Alarm(this, 'LambdaErrorAlarm', {
      metric: apiLambda.metricErrors(),
      threshold: 5,
      evaluationPeriods: 2,
    });
  

    // ====================== AUTH ======================
    // User Pool — for human users (web/mobile login)
    const userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: 'telemetry-users',
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 8,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    
    // App client for human users
    const userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool,
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      generateSecret: false, // false for web/mobile clients
    });
    
    // Resource server — defines the API scope
    const resourceServer = new cognito.UserPoolResourceServer(this, 'ResourceServer', {
      userPool,
      identifier: 'telemetry-api',
      scopes: [
        new cognito.ResourceServerScope({ scopeName: 'write', scopeDescription: 'Write telemetry' }),
        new cognito.ResourceServerScope({ scopeName: 'read', scopeDescription: 'Read telemetry' }),
      ],
    });
    
    // App client for machine-to-machine (devices) — client credentials flow
    const deviceClient = new cognito.UserPoolClient(this, 'DeviceClient', {
      userPool,
      authFlows: {},
      generateSecret: true, // devices use client secret
      oAuth: {
        flows: { clientCredentials: true },
        scopes: [
          cognito.OAuthScope.resourceServer(resourceServer, 
            new cognito.ResourceServerScope({ scopeName: 'write', scopeDescription: 'Write telemetry' })
          ),
        ],
      },
    });
    
    // Cognito domain for token endpoint
    const userPoolDomain = new cognito.UserPoolDomain(this, 'UserPoolDomain', {
      userPool,
      cognitoDomain: {
        domainPrefix: 'telemetry-demo-eyespan', // must be globally unique
      },
    });
    
    // ====================== API GATEWAY AUTHORIZER ======================
    /*const authorizer = new apigw.CognitoUserPoolsAuthorizer(this, 'CognitoAuthorizer', {
      cognitoUserPools: [userPool],
      identitySource: 'method.request.header.Authorization', // ← explicit header source
    });
    
   
    // Update your existing routes to require auth
    devices.addMethod('POST', new apigw.LambdaIntegration(apiLambda), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    devices.addMethod('GET', new apigw.LambdaIntegration(apiLambda), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });*/

                // ====================== LAMBDA AUTHORIZER ======================
    const authorizerLambda = new lambda.Function(this, 'AuthorizerHandler', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/authorizer'),
      // memorySize: 256, // ← increase from 128MB
      timeout: cdk.Duration.seconds(120),
      environment: {
        USER_POOL_ID: userPool.userPoolId,
    },
    // No VPC needed — only calls Cognito JWKS endpoint (public)
    });

    const lambdaAuthorizer = new apigw.TokenAuthorizer(this, 'LambdaAuthorizer', {
      handler: authorizerLambda,
      identitySource: 'method.request.header.Authorization',
      resultsCacheTtl: cdk.Duration.minutes(5), // cache valid tokens for 5 min
    });

  // Replace authorizer on both methods
    devices.addMethod('POST', new apigw.LambdaIntegration(apiLambda), {
      authorizer: lambdaAuthorizer,
      authorizationType: apigw.AuthorizationType.CUSTOM,
    });

    devices.addMethod('GET', new apigw.LambdaIntegration(apiLambda), {
      authorizer: lambdaAuthorizer,
      authorizationType: apigw.AuthorizationType.CUSTOM,
    });

    
    devices.addMethod('OPTIONS', new apigw.MockIntegration({
      integrationResponses: [{
        statusCode: '200',
        responseParameters: {
          'method.response.header.Access-Control-Allow-Headers': "'Content-Type,Authorization,X-Amz-Date,X-Api-Key'",
          'method.response.header.Access-Control-Allow-Methods': "'GET,POST,OPTIONS'",
          'method.response.header.Access-Control-Allow-Origin':  "'*'",
        },
      }],
      passthroughBehavior: apigw.PassthroughBehavior.NEVER,
      requestTemplates: { 'application/json': '{"statusCode": 200}' },
    }), {
      authorizationType: apigw.AuthorizationType.NONE,  // ← no auth on OPTIONS
      methodResponses: [{
        statusCode: '200',
        responseParameters: {
          'method.response.header.Access-Control-Allow-Headers': true,
          'method.response.header.Access-Control-Allow-Methods': true,
          'method.response.header.Access-Control-Allow-Origin':  true,
        },
      }],
    });
    
    // ====================== OUTPUTS ======================
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'DeviceClientId', { value: deviceClient.userPoolClientId });
    new cdk.CfnOutput(this, 'CognitoDomain', { 
      value: `https://${userPoolDomain.domainName}.auth.us-east-1.amazoncognito.com` 
    });
  
    
    // ====================== IOT CORE ======================
    
    // IoT Thing — represents a physical device
    const iotThing = new iot.CfnThing(this, 'DemoDevice', {
      thingName: 'demo-device-001',
    });
    
    // IoT Policy — what the device is allowed to do
    const iotPolicy = new iot.CfnPolicy(this, 'DevicePolicy', {
      policyName: 'TelemetryDevicePolicy',
      policyDocument: {
        Version: '2012-10-17',
        Statement: [
          {
            Effect: 'Allow',
            Action: 'iot:Connect',
            Resource: `arn:aws:iot:${this.region}:${this.account}:client/\${iot:ClientId}`,
          },
          {
            Effect: 'Allow',
            Action: 'iot:Publish',
            Resource: `arn:aws:iot:${this.region}:${this.account}:topic/devices/*/telemetry`,
          },
          {
            Effect: 'Allow',
            Action: 'iot:Subscribe',
            Resource: `arn:aws:iot:${this.region}:${this.account}:topicfilter/devices/*/telemetry`,
          },
        ],
      },
    });
    
    // Generate certificate via custom resource
    const certResource = new cr.AwsCustomResource(this, 'IotCertificate', {
      onCreate: {
        service: 'Iot',
        action: 'createKeysAndCertificate',
        parameters: { setAsActive: true },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('certificateId'),
      },
      onDelete: {
        service: 'Iot',
        action: 'updateCertificate',
        parameters: {
          certificateId: new cr.PhysicalResourceIdReference(),
          newStatus: 'INACTIVE',
        },
      },
      policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
        resources: cr.AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
    });
    
    // Attach certificate to thing
    new iot.CfnThingPrincipalAttachment(this, 'ThingCertAttachment', {
      thingName: iotThing.thingName!,
      principal: certResource.getResponseField('certificateArn'),
    });
    
    // Attach policy to certificate
    new iot.CfnPolicyPrincipalAttachment(this, 'PolicyCertAttachment', {
      policyName: iotPolicy.policyName!,
      principal: certResource.getResponseField('certificateArn'),
    });
    
    // ====================== IOT INGEST LAMBDA ======================
    const iotLambda = new lambda.Function(this, 'IotIngestHandler', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/iot'),
      role: lambdaRole, // reuse existing role
      timeout: cdk.Duration.seconds(30),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      environment: {
        TABLE_NAME: telemetryTable.tableName,
        QUEUE_URL: processingQueue.queueUrl,
        TIMESTREAM_DB: 'telemetry_ts',
        TIMESTREAM_TABLE: 'metrics',
        NODE_ENV: 'production',
      },
    });
    
    // Allow IoT Core to invoke the Lambda
    iotLambda.addPermission('IotInvokePermission', {
      principal: new iam.ServicePrincipal('iot.amazonaws.com'),
      sourceArn: `arn:aws:iot:${this.region}:${this.account}:rule/*`,
    });
    

   // ====================== IOT CLOUDWATCH ROLE ======================
  // Separate role for IoT Core to write error logs — IoT cannot assume the Lambda role
    const iotLoggingRole = new iam.Role(this, 'IotLoggingRole', {
      assumedBy: new iam.ServicePrincipal('iot.amazonaws.com'), // ← IoT trust policy
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSIoTLogging'),
      ],
    });

    // IoT Topic Rule — routes MQTT messages to Lambda
    const iotRule = new iot.CfnTopicRule(this, 'TelemetryRule', {
      ruleName: 'TelemetryIngestRule',
      topicRulePayload: {
        sql: "SELECT *, topic(2) as deviceId FROM 'devices/+/telemetry'",
        awsIotSqlVersion: '2016-03-23',
        actions: [
          {
            lambda: {
              functionArn: iotLambda.functionArn,
            },
          },
        ],
        errorAction: {
          cloudwatchLogs: {
            logGroupName: '/aws/iot/errors',
            roleArn: iotLoggingRole.roleArn, // ← was lambdaRole.roleArn
          },
        },
      },
    });
    
    // ====================== OUTPUTS ======================
    new cdk.CfnOutput(this, 'IotThingName', { value: iotThing.thingName! });
    new cdk.CfnOutput(this, 'IotCertificateArn', { 
      value: certResource.getResponseField('certificateArn') 
    });
    new cdk.CfnOutput(this, 'IotCertificatePem', { 
      value: certResource.getResponseField('certificatePem') 
    });
    new cdk.CfnOutput(this, 'IotPrivateKey', { 
      value: certResource.getResponseField('keyPair.PrivateKey') 
    });

          // ── Query Lambda ──────────────────────────────────────────────
    const queryLambda = new lambda.Function(this, 'QueryHandler', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/query'),
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      // memorySize: 256,
      environment: {
        NODE_ENV: 'production',
        TIMESTREAM_QUERY_ENDPOINT: `vpce-0a0a51401d7d2e43a-735mhmzl.query-cell2.timestream.us-east-1.vpce.amazonaws.com`
      },
  // No VPC — Timestream query endpoint is public
    });

    // Add timestream:Select permission to existing role
    lambdaRole.addToPolicy(new iam.PolicyStatement({
        actions: [
      'timestream:Select',
    'timestream:DescribeEndpoints',
    'timestream:SelectValues',
  ],
  resources: ['*'],
    }));

    // ── API routes ────────────────────────────────────────────────
    // Remove defaultCorsPreflightOptions from the API definition
// and manually add OPTIONS to each resource without an authorizer

const metrics = api.root.addResource('metrics');

metrics.addMethod('GET', new apigw.LambdaIntegration(queryLambda), {
  authorizer: lambdaAuthorizer,
  authorizationType: apigw.AuthorizationType.CUSTOM,
});

// OPTIONS with no authorizer — handles CORS preflight
metrics.addMethod('OPTIONS', new apigw.MockIntegration({
  integrationResponses: [{
    statusCode: '200',
    responseParameters: {
      'method.response.header.Access-Control-Allow-Headers': "'Content-Type,Authorization,X-Amz-Date,X-Api-Key'",
      'method.response.header.Access-Control-Allow-Methods': "'GET,POST,OPTIONS'",
      'method.response.header.Access-Control-Allow-Origin':  "'*'",
    },
  }],
  passthroughBehavior: apigw.PassthroughBehavior.NEVER,
  requestTemplates: { 'application/json': '{"statusCode": 200}' },
}), {
  authorizationType: apigw.AuthorizationType.NONE,  // ← no auth on OPTIONS
  methodResponses: [{
    statusCode: '200',
    responseParameters: {
      'method.response.header.Access-Control-Allow-Headers': true,
      'method.response.header.Access-Control-Allow-Methods': true,
      'method.response.header.Access-Control-Allow-Origin':  true,
    },
  }],
});



    // ── Cognito hosted UI callback URL ────────────────────────────
    const cfDomain = `https://${distribution.distributionDomainName}`;

    userPool.addClient('DashboardClient', {
      userPoolClientName: 'telemetry-dashboard',
      authFlows: { userSrp: true },
      generateSecret: false,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        callbackUrls: [cfDomain, 'http://localhost:3000'],
        logoutUrls:   [cfDomain, 'http://localhost:3000'],
      },
    });

    // ── Outputs ───────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'DashboardUrl', {
  value: cfDomain,
  description: 'CloudFront dashboard URL',
    });

  new cdk.CfnOutput(this, 'MetricsApiEndpoint', {
  value: `${api.url}metrics`,
  description: 'Metrics query endpoint',
  });

  

  // ====================== GRAFANA EC2 ======================

// ====================== SSM VPC ENDPOINTS ======================
// Required for SSM Session Manager in private subnet
vpc.addInterfaceEndpoint('SsmEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.SSM,
  privateDnsEnabled: true,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});

vpc.addInterfaceEndpoint('SsmMessagesEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
  privateDnsEnabled: true,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});

vpc.addInterfaceEndpoint('Ec2MessagesEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
  privateDnsEnabled: true,
  subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
});

// ====================== UPLOAD GRAFANA ARTIFACTS TO S3 ======================
// Run this once locally before cdk deploy:
// curl -O https://dl.grafana.com/oss/release/grafana-11.1.0-1.x86_64.rpm
// grafana-cli --pluginsDir /tmp/grafana-plugins plugins install grafana-timestream-datasource
// Then CDK will upload them to S3 automatically

/*new s3deploy.BucketDeployment(this, 'GrafanaArtifacts', {
  sources: [s3deploy.Source.asset('./grafana-artifacts')], // ← local folder
  destinationBucket: assetBucket,
  destinationKeyPrefix: 'grafana/',
  prune: false,
});*/

// ====================== GRAFANA SECURITY GROUP ======================

const grafanaSg = new ec2.SecurityGroup(this, 'GrafanaSg', {
  vpc,
  description: 'Grafana EC2 private subnet ALB access only', // ← no special characters
  allowAllOutbound: true,
});

// Only allow traffic from ALB (added when ALB is created)
// No SSH ingress — use SSM Session Manager instead

// ====================== GRAFANA IAM ROLE ======================
const grafanaRole = new iam.Role(this, 'GrafanaRole', {
  assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonTimestreamReadOnlyAccess'),
    iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'), // ← SSM access
  ],
});

// Allow EC2 to read from S3 bucket (for Grafana artifacts)
assetBucket.grantRead(grafanaRole);

// ====================== GRAFANA EC2 ======================
const grafanaInstance = new ec2.Instance(this, 'GrafanaInstance', {
  vpc,
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS}, // ← private, no public IP
  instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
  machineImage: ec2.MachineImage.latestAmazonLinux2023(),
  securityGroup: grafanaSg,
  role: grafanaRole,
  // ← no keyPair — SSM only
  requireImdsv2: true,
  userData: ec2.UserData.forLinux(),
});

// ── User data — installs from S3, no internet needed ──────────
grafanaInstance.userData.addCommands(
  'set -e',
  'exec > /var/log/grafana-install.log 2>&1',

  // Install Grafana
  'dnf install -y https://dl.grafana.com/oss/release/grafana-11.1.0-1.x86_64.rpm',
  
  // Install Timestream plugin with correct plugin dir
  'GF_PLUGIN_DIR=/var/lib/grafana/plugins grafana-cli plugins install grafana-timestream-datasource',

  // Fix permissions so Grafana can read the plugin
  'chown -R grafana:grafana /var/lib/grafana/plugins/',
  'chmod -R 755 /var/lib/grafana/plugins/',


  // Pull Grafana RPM from S3 via VPC gateway endpoint - the rpm is too big (116MB) to upload to an s3 bucket 
  //`aws s3 cp s3://${assetBucket.bucketName}/grafana/grafana-11.1.0-1.x86_64.rpm /tmp/ --region ${this.region}`,
  //'dnf install -y /tmp/grafana-11.1.0-1.x86_64.rpm',

  // Pull Timestream plugin from S3
  //'mkdir -p /var/lib/grafana/plugins',
  //`aws s3 cp s3://${assetBucket.bucketName}/grafana/plugins/ /var/lib/grafana/plugins/ --recursive --region ${this.region}`,

  // Fix permissions
  'chown -R grafana:grafana /var/lib/grafana/plugins/',
  'chmod -R 755 /var/lib/grafana/plugins/',

  // Configure Grafana
  'cat > /etc/grafana/grafana.ini << EOF',
  '[server]',
  'http_port = 3000',
  '[security]',
  'admin_user = admin',
  'admin_password = TelemetryOS2026!',
  '[auth.anonymous]',
  'enabled = false',
  'EOF',

  // Enable and start
  'systemctl daemon-reload',
  'systemctl enable grafana-server',
  'systemctl start grafana-server',

  'echo "Grafana install complete"',
);

// ====================== ALB ======================
const albSg = new ec2.SecurityGroup(this, 'AlbSg', {
  vpc,
  description: 'ALB security group',
  allowAllOutbound: true,
});

//albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');
albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80),  'HTTP redirect');

// Allow ALB to reach Grafana on port 3000
grafanaSg.addIngressRule(albSg, ec2.Port.tcp(3000), 'ALB to Grafana');

const alb = new elbv2.ApplicationLoadBalancer(this, 'GrafanaAlb', {
  vpc,
  internetFacing: true,
  vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
  securityGroup: albSg,
});

const targetGroup = new elbv2.ApplicationTargetGroup(this, 'GrafanaTg', {
  vpc,
  port: 3000,
  protocol: elbv2.ApplicationProtocol.HTTP,
  targets: [new elbv2targets.InstanceTarget(grafanaInstance)],
  healthCheck: {
    path:                '/api/health',
    healthyHttpCodes:    '200',
    interval:            cdk.Duration.seconds(30),
    timeout:             cdk.Duration.seconds(10),
    healthyThresholdCount:   2,
    unhealthyThresholdCount: 3,
  },
});

// HTTP → HTTPS redirect
/*alb.addListener('HttpListener', {
  port: 80,
  defaultAction: elbv2.ListenerAction.redirect({
    protocol: 'HTTPS',
    port:     '443',
    permanent: true,
  }),
});*/

alb.addListener('HttpListener', {
  port: 80,
  protocol: elbv2.ApplicationProtocol.HTTP,
  defaultTargetGroups: [targetGroup],
});

// HTTPS listener — uses ALB default cert (no custom domain needed)
/*alb.addListener('HttpsListener', {
  port: 443,
  protocol: elbv2.ApplicationProtocol.HTTPS,
  certificates: [elbv2.ListenerCertificate.fromArn(
    // ← we'll use a self-signed cert via ACM for demo
    new acm.Certificate(this, 'GrafanaCert', {
      domainName: alb.loadBalancerDnsName,
      validation: acm.CertificateValidation.fromDns(),
    }).certificateArn
  )],
  defaultTargetGroups: [targetGroup],
});*/



// ====================== OUTPUTS ======================
new cdk.CfnOutput(this, 'GrafanaAlbUrl', {
  value: `https://${alb.loadBalancerDnsName}`,
  description: 'Grafana ALB URL',
});

new cdk.CfnOutput(this, 'GrafanaInstanceId', {
  value: grafanaInstance.instanceId,
  description: 'SSM access: aws ssm start-session --target <instance-id>',
});            
  }
   
}

