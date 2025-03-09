## Sportscanner - search and compare playing venues
![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/crawler-pipeline.yml/badge.svg) ![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/Automated-PR-tests.yml/badge.svg) ![example workflow](https://github.com/sportscanner/app-crawlers/actions/workflows/deploy-to-registry.yml/badge.svg)

 
### What is it about?
Finding racket sports courts in London, like squash, badminton, or tennis, can be challenging, especially without an expensive club membership. While there are several "pay and play" options available, the process of finding courts and checking their availability is often frustrating. Players end up going to multiple websites/links to look up court availability near them - and thus the need for a centralised solution.

### System design and roadmap
The frontend is a `Next.js` powered app that is deployed using `Vercel`, and the backend is split into 2 components: **Crawlers** are python based scripts ran using a scheduled `Github Actions` job that parses availability and stores in a centralised postgres database; and the **Sportscanner API** is a `FastAPI` based server deployed via *Render serverless cloud* and is responsible for interacting with frontend, aligning multiple venue schemas, personalisations and advanced filtering 

![diagram-export-09-03-2025-15_48_11](https://github.com/user-attachments/assets/9b191a01-ecc1-4c9e-9fdb-d8fe4a8b2698)



## Authors
- [Yasir Khalid](https://www.linkedin.com/in/yasir-khalid)
