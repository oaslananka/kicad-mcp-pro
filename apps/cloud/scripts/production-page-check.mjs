import assert from "node:assert/strict";

export function assertLandingStructuredData(page,origin){
  assert.equal((page.match(/<script\b/gi)??[]).length,1,
    "Public landing permits only its inert structured data");
  const metadata=/<script type="application\/ld\+json">([\s\S]*?)<\/script>/i.exec(page);
  assert.ok(metadata,"Landing structured data must be inert JSON-LD without extra attributes");
  const schema=JSON.parse(metadata[1]);
  assert.equal(schema["@context"],"https://schema.org");
  assert.equal(schema["@type"],"SoftwareApplication");
  assert.equal(schema.url,origin+"/");
}
