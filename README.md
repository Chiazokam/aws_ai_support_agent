# Screenshots & Reflections

### Screenshots
##### Test 1 (Order Tracking)
![Test 1 Screenshot](/screenshots/Test_1_order_tracking.png)
##### Test 2 (Refund Processing)
![Test 2 Screenshot](/screenshots/Test_2_refund_processing.png)
##### Test 3 (Knowledge Base - RAG)
![Test 3 Screenshot](/screenshots/Test_3_knowledge_base_RAG.png)
##### Test 4 (Long Term Memory - Session 1)
![Test 4 - Session 1 Screenshot](/screenshots/Test_4_long_term_memory_session_1.png)
##### Test 4 (Long Term Memory - Session 2)
![Test 4 - Stopping Session 1 & Session 2 Screenshot](/screenshots/Test_4_long_term_memory_session_2.png)
##### Test 5 (Loyalty Discount Calculation)
![Test 5 Screenshot](/screenshots/Test_5_loyalty_discount_calculation.png)
##### Test 6 (Browser Tool)
![Test 6 Screenshot](/screenshots/Test_6_browser_tool.png)


### Reflections
 - ##### Design Decision
 I would like to talk about the Long term memory integration. If I were to integrate this agent into a companies website to help with user requests, using long term memory in this case is necessary for a good user experience. If a user has specified some information or the agent has captured some information about a customer, it would be lovely that if the customer closes the session and comes back days/weeks later, the agent can still remember his preferences/tone.

 - ##### Challenges Encountered
 I was following the scripts shared on the Project's instruction page, then got to the place of deploying the agent. I observed that scripts starting with `agentcore ...` were not running until I prefixed them with `uv run agentcore...`

 When I first cloned the project starter, there was no `setup_permissions.py`. So, going straight to start invoking the agent after deploying resulted in some errors. 
 I was able to pick the cause of these errors by visiting the logs on cloudwatch. I could then tell that some access was being denied. This I was able to handle when I saw that the starter repo had been updated with the `setup_permissions.py` file.

 - ##### Production Consideration
 To extend this project for production, I would script all the resource provisioning processes, so that it would be easy to start up the agent or even replicate it if there is a need.
 