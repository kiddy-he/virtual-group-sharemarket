/** Run a harmless synthetic private /fx message against a local example market. */
import {readFile} from 'node:fs/promises';
import {createMarketAdapter} from '../sdk/adapter.mjs';
const config=JSON.parse(await readFile(new URL('../config/bot.example.json',import.meta.url),'utf8'));
const adapter=createMarketAdapter(config);
const response=await adapter.handle({accountId:'bot',senderId:'700000001',scope:'private',messageId:'local-example-'+Date.now(),text:process.argv[2]??'/fx 帮助',nickname:'示例玩家'});
if(response.needsClarification)console.log(response.text);
else{
  console.log(response.result.text);
  console.log('Destination:',response.destination);
  console.log('All chart pages:',await adapter.artifacts(response));
  // A real host sends every page to response.destination, then ACKs with its receipt.
  // This diagnostic example intentionally does not send chat messages or acknowledge.
}
