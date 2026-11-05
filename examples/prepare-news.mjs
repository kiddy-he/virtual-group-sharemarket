import {readFile} from 'node:fs/promises';
import {createJsonModel} from '../sdk/llm.mjs';
import {produceNews} from '../sdk/news-producer.mjs';
const path=process.argv[2];if(!path)throw Error('Usage: node examples/prepare-news.mjs config/local.json');
const config=JSON.parse(await readFile(path,'utf8'));
if(!config.llm?.enabled||!config.news?.enabled)throw Error('Enable news and configure an optional model first');
console.log(await produceNews(config,{request:createJsonModel(config.llm)}));
// Schedule this as a bounded one-shot worker. It prepares articles only; it never posts.
