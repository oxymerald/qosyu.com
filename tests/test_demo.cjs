const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");

function sandbox(role="sme") {
  const context=vm.createContext({URL,structuredClone,state:{demo:role},t:key=>key});
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../app/static/js/demo.js"),"utf8"),context);
  return {context,api:vm.runInContext("QosyuDemo",context)};
}

test("demo lifecycle creates, assigns and completes only fictional data",async()=>{
  const {context,api}=sandbox();
  assert.equal((await api.request("/requests/my")).length,6);
  const created=await api.request("/requests/create","POST",{waste_type:"cardboard",weight_kg:10,latitude:47.12,longitude:51.89});
  assert.equal(created.status,"pending");
  context.state.demo="recycler";
  await api.request("/clustering/generate-zones","POST");
  assert.equal((await api.request("/clustering/zones/open")).length,2);
  const route=await api.request("/recycler/zones/1/route");
  assert.equal(route.stops.length,6);assert.equal(route.total_weight_kg,90);
  assert.equal(route.approximate,true);
  const filtered=await api.request("/recycler/map-requests?min_kg=15&max_kg=15&status=clustered&q=demo.point%201");
  assert.equal(filtered.items.length,1);
  assert.equal(filtered.items[0].id,1);
  await api.request("/recycler/zones/1/assign","POST");
  assert.equal((await api.request("/recycler/zones/my")).length,1);
  await api.request("/recycler/zones/1/complete","POST",{actual_weight_kg:88});
  const history=await api.request("/recycler/zones/completed");
  assert.equal(history.length,1);
  assert.equal(history[0].actual_weight_kg,88);
  assert.equal((await api.request("/auth/features")).telegram_enabled,false);
  context.state.demo="sme";
  const metrics=await api.request("/analytics/esg/sme");
  assert.equal(metrics.total_recycled_kg,90);
  assert.equal(metrics.co2_saved_kg,28.35);
});

test("unknown, privileged and AI actions fail closed without a network fallback",async()=>{
  const {api}=sandbox();
  for(const endpoint of ["/admin/stats","/auth/change-password","/recycler/zones/1/route","/ai/assistant"]) {
    await assert.rejects(api.request(endpoint,"POST"));
  }
  assert.equal((await api.request("/ai/status")).available,false);
  assert.equal(api.user("sme").id<0,true);
});

test("cancellation cannot remove a clustered request",async()=>{
  const {api}=sandbox();
  await assert.rejects(api.request("/requests/1","DELETE"));
  const request=await api.request("/requests/create","POST",{weight_kg:10,latitude:47.12,longitude:51.89});
  await api.request(`/requests/${request.id}`,"DELETE");
  assert.equal((await api.request("/requests/my")).length,6);
});
