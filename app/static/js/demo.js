"use strict";

// No token, password, real database access or external AI calls in this sandbox.
const QosyuDemo = (() => {
  let requests = null;
  let zones = [];
  let nextId = 7;
  const CARDBOARD_CO2E_PER_KG = 0.315;
  const base = { lat: 47.1167, lon: 51.8833 };
  const user = role => ({ id: role === "sme" ? -101 : -102, role,
    company_name: t(role === "sme" ? "demo.businessName" : "demo.recyclerName"),
    email: `${role}@demo.example`, is_active: true });

  function seed() {
    if (requests) return;
    requests = [[47.12,51.885],[47.123,51.89],[47.126,51.895],
      [47.12,51.903],[47.115,51.899],[47.112,51.89]].map(([latitude,longitude],i) => ({
      id: i + 1, sme_id: -101, waste_type: "cardboard", weight_kg: 15,
      latitude, longitude, address: `${t("demo.point")} ${i + 1}`,
      pickup_note: t("demo.notice"), status: "clustered", created_at: new Date().toISOString(),
    }));
    zones = [{ id: 1, request_ids: requests.map(r=>r.id), status: "open", recycler_id: null,
      centroid_lat: 47.12, centroid_lon: 51.895, radius_km: 1.5, total_weight_kg: 90, request_count: 6 }];
  }

  function route(zone, params) {
    const start = params.has("start_lat") ? {lat: Number(params.get("start_lat")), lon: Number(params.get("start_lon"))} : base;
    const stops = zone.request_ids.map((id,i) => {
      const r=requests.find(r=>r.id===id);
      return { ...r, request_id:r.id, order:i+1, lat:r.latitude, lon:r.longitude, company:t("demo.businessName") };
    });
    const geometry=[[start.lat,start.lon],...stops.map(s=>[s.lat,s.lon]),[start.lat,start.lon]];
    const rad=x=>x*Math.PI/180;
    let distance=0;
    for(let i=1;i<geometry.length;i++) {
      const [a,b]=geometry[i-1], [c,d]=geometry[i];
      const h=Math.sin(rad(c-a)/2)**2+Math.cos(rad(a))*Math.cos(rad(c))*Math.sin(rad(d-b)/2)**2;
      distance+=6371*2*Math.asin(Math.min(1,Math.sqrt(h)));
    }
    return { zone_id:zone.id, start, stops, geometry, distance_km:Number(distance.toFixed(2)),
      duration_min:Math.round(distance/30*60+stops.length*6), total_weight_kg:zone.total_weight_kg,
      approximate:true, source:"heuristic", order_source:"geographic" };
  }

  async function request(endpoint,method="GET",body=null) {
    seed();
    const url=new URL(endpoint,"https://demo.invalid"), path=url.pathname;
    const role=state.demo;
    if(method==="GET") {
      if(path==="/maps/status") return {provider:"osm"};
      if(path==="/maps/search") return {items:requests.map(r=>({lat:r.latitude,lon:r.longitude,name:r.address}))};
      if(path==="/requests/my") {
        if(role!=="sme") return [];
        const offset=Number(url.searchParams.get("offset")||0), limit=Number(url.searchParams.get("limit")||50);
        return structuredClone(requests.slice(offset,offset+limit));
      }
      if(path==="/clustering/zones/open") return structuredClone(zones.filter(z=>z.status==="open"));
      if(path==="/recycler/zones/my") return structuredClone(zones.filter(z=>z.recycler_id===-102&&z.status==="assigned"));
      if(path==="/recycler/map-requests" && role==="recycler") {
        const params = url.searchParams;
        const minimum = Number(params.get("min_kg") ?? 0);
        const maximum = Number(params.get("max_kg") ?? Infinity);
        const status = params.get("status");
        const needle = (params.get("q") || "").trim().toLowerCase();
        const items = [];
        for (const zone of zones) {
          if (zone.status !== "open" && zone.recycler_id !== -102) continue;
          for (const pickup of requests) {
            if (!zone.request_ids.includes(pickup.id)) continue;
            if (pickup.weight_kg < minimum || pickup.weight_kg > maximum) continue;
            if (status && pickup.status !== status) continue;
            if (needle && ![pickup.address, pickup.pickup_note].some(value => value?.toLowerCase().includes(needle))) continue;
            items.push({ ...pickup, zone_id: zone.id });
          }
        }
        return { items: structuredClone(items), truncated: false };
      }
      if(path==="/analytics/esg/sme") {
        const collected = requests.filter(request => request.status === "collected");
        const total = collected.reduce((kg, request) => kg + request.weight_kg, 0);
        const cardboard = collected.filter(request => request.waste_type === "cardboard")
          .reduce((kg, request) => kg + request.weight_kg, 0);
        const cents = cardboard * CARDBOARD_CO2E_PER_KG * 100;
        const co2 = Math.round(cents + Number.EPSILON * cents) / 100;
        return {total_recycled_kg:total, co2_saved_kg:co2,
          co2_factor:CARDBOARD_CO2E_PER_KG, equivalent_trees:Number((co2 / 22).toFixed(1))};
      }
      if(path==="/chat/unread-count") return {unread:0};
      if(["/chat/conversations","/chat/partners","/marketplace/listings","/marketplace/orders/my"].includes(path)) return [];
      if(path==="/ai/status") return {available:false,provider:"demo",map_tools:false};
      const match=path.match(/^\/recycler\/zones\/(\d+)\/route$/);
      if(match&&role==="recycler") {
        const zone=zones.find(z=>z.id===Number(match[1]));
        if(zone) return route(zone,url.searchParams);
      }
    }
    if(method==="POST"&&path==="/requests/create"&&role==="sme") {
      if(requests.length>=100) throw new Error(t("demo.unavailable"));
      const r={...structuredClone(body),id:nextId++,sme_id:-101,status:"pending",created_at:new Date().toISOString()};
      requests.unshift(r);return structuredClone(r);
    }
    if(method==="DELETE"&&path.startsWith("/requests/")&&role==="sme") {
      const id=Number(path.split("/").pop()), r=requests.find(r=>r.id===id);
      if(!r||r.status!=="pending") throw new Error(t("demo.unavailable"));
      requests=requests.filter(r=>r.id!==id);return null;
    }
    if(method==="POST"&&path==="/clustering/generate-zones"&&role==="recycler") {
      const pending=requests.filter(r=>r.status==="pending");
      if(pending.length) {
        const id=Math.max(0,...zones.map(z=>z.id))+1;
        zones.push({id,request_ids:pending.map(r=>r.id),status:"open",recycler_id:null,
          centroid_lat:pending[0].latitude,centroid_lon:pending[0].longitude,radius_km:1.5,
          total_weight_kg:pending.reduce((n,r)=>n+r.weight_kg,0),request_count:pending.length});
        pending.forEach(r=>r.status="clustered");
      }
      return {message:`${t("demo.zoneCount")}: ${pending.length?1:0}`,zones_created:pending.length?1:0};
    }
    const change=path.match(/^\/recycler\/zones\/(\d+)\/(assign|complete)$/);
    if(method==="POST"&&change&&role==="recycler") {
      const zone=zones.find(z=>z.id===Number(change[1]));
      if(!zone||(change[2]==="assign"?zone.status!=="open":zone.status!=="assigned")) throw new Error(t("demo.unavailable"));
      zone.status=change[2]==="assign"?"assigned":"completed";zone.recycler_id=-102;
      requests.filter(r=>zone.request_ids.includes(r.id)).forEach(r=>r.status=change[2]==="assign"?"assigned":"collected");
      return {message:"OK"};
    }
    // Fail closed: an unknown sandbox action must never reach the real API.
    throw new Error(t("demo.unavailable"));
  }

  return {user,request};
})();
