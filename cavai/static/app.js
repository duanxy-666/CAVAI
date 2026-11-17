"use strict";
const $ = id => document.getElementById(id);
const state = { id:null, mesh:null, yaw:0.62, pitch:0.42, zoom:1.0,
                drag:false, x:0,y:0, running:false };
const models = {
  DeepSeek:{url:"https://api.deepseek.com",name:"deepseek-chat"},
  OpenAI:{url:"https://api.openai.com/v1",name:"gpt-4.1-mini"},
  Compatible:{url:"https://your-provider.example/v1",name:"model-name"}
};
const statusText = {pass:"通过",fail:"不满足",review:"待复核",unverified:"未验证",info:"实测信息"};
const structuralText={fail:"检测到结构问题",basic_checks_passed:"基础结构检查通过",unknown:"结构证据不足"};
const functionalText={fail_specific_requirement:"不符合部分明确要求",partial_requirements_met:"部分明确要求通过",unknown:"完整功能适用性未验证"};

$("provider").addEventListener("change",()=>{const p=models[$("provider").value];$("baseUrl").value=p.url;$("modelName").value=p.name;});
$("fileInput").addEventListener("change",()=>{let file=$("fileInput").files[0];if(file)$("fileLabel").textContent=file.name;});
const drop=$("dropZone");
["dragenter","dragover"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("dragging");}));
["dragleave","drop"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove("dragging");}));
drop.addEventListener("drop",e=>{
  if(e.dataTransfer?.files?.length){
    $("fileInput").files=e.dataTransfer.files;
    $("fileLabel").textContent=e.dataTransfer.files[0].name;
  }
});

function setState(label,style=""){$("runState").textContent=label;$("runState").className="state-label "+style;}
function busy(button, on, text){
  if(on){button.dataset.normalText=button.textContent;button.disabled=true;button.textContent=text;}
  else{button.textContent=button.dataset.normalText||button.textContent;button.disabled=false;}
}
function makeText(tag,text,cls){
  const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;
}
function logEvent(type,title,detail=""){
  let box=$("timeline");
  if(box.querySelector(".timeline-empty"))box.replaceChildren();
  let item=makeText("div","","event "+type);
  item.appendChild(makeText("strong",title));
  if(detail)item.appendChild(makeText("small",detail));
  box.appendChild(item);box.scrollTop=box.scrollHeight;
}
function readable(n,d=2){return typeof n==="number"?n.toLocaleString("en-US",{maximumFractionDigits:d}):"—";}
function showSummary(summary,filename){
  const bbox=summary.bounds_mm||summary.bounding_box?.size||[];
  const unit=summary.units==="unknown"?"(单位未知)":"mm";
  const native=summary.catia_native;
  const geometryAvailable=summary.geometry_type==="brep"||summary.geometry_type==="mesh";
  const nativeCount=native?`${native.bodies?.count??"?"} Body / ${native.parameters?.count??"?"} 参数`:null;
  const arr=[
    (bbox.length===3?bbox.map(x=>readable(x,2)).join(" × "):"未取得")+" "+unit,
    summary.volume_mm3==null?"未取得":readable(summary.volume_mm3,2)+" mm³",
    summary.geometry_type==="brep"?`${summary.solid_count} 实体 / ${summary.face_count} 面`:
      summary.geometry_type==="mesh"?`${summary.mesh_face_count} 三角面`:
      (nativeCount||"未取得")
  ];
  [...$("modelStats").children].forEach((div,i)=>{div.querySelector("strong").textContent=arr[i];});
  $("previewStatus").textContent=filename;
  const exportStatus=native?`；CATIA 自动几何导出：${native.geometry_export?.status==="success"?"成功":"不可用"}`:"";
  $("modelDisclaimer").textContent=(summary.unit_note||"")
      +"；原生特征信息："+(summary.parameter_tree_available?"已读取（非完整依赖图）":"不可用")
      +exportStatus+"。"+(geometryAvailable?
          "三维预览来自真实 CAD 内核几何网格。":
          "无法提供三维预览或有效的几何合格判定。");
}
async function getJson(url,opts={}){
  const r=await fetch(url,opts);
  let data;try{data=await r.json();}catch(_){data={detail:"HTTP "+r.status};}
  if(!r.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail)||("HTTP "+r.status));
  return data;
}
$("uploadBtn").addEventListener("click",async()=>{
  const f=$("fileInput").files?.[0];if(!f){alert("请先选择 CAD 文件");return;}
  const form=new FormData();
  form.append("file",f);form.append("description",$("description").value);
  form.append("source_prompt",$("sourcePrompt").value);
  form.append("requirements_json",$("requirements").value||"{}");
  form.append("stl_units",$("stlUnits").value);
  busy($("uploadBtn"),true,"正在读取 CATIA / CAD ...");
  state.id=null;state.mesh=null;$("inspectBtn").disabled=true;
  $("offlineBtn").disabled=true;$("results").classList.add("hidden");
  setState("解析中","busy");
  $("timeline").replaceChildren();
  logEvent("phase","开始上传与几何内核解析",f.name);
  try{
    const info=await getJson("/api/upload",{method:"POST",body:form});
    state.id=info.model_id;
    showSummary(info.summary,info.filename);
    logEvent("tool","CAD 解析完成","SHA256 "+info.sha256.slice(0,18)+"…");
    state.mesh=await getJson("/api/models/"+state.id+"/preview");
    const has3d=Array.isArray(state.mesh.faces)&&state.mesh.faces.length>0;
    $("viewerEmpty").classList.toggle("hidden",has3d);
    if(has3d){
      fitCanvas();renderViewer();
      logEvent("tool","已读取真实几何 / 网格预览",`${state.mesh.display_triangles} 个预览三角面`);
    }else{
      $("viewerEmpty").querySelector("strong").textContent="CATIA 原生结构已读取";
      $("viewerEmpty").querySelector("span").textContent="尚无可预览几何：自动 STEP/IGES 导出不可用";
      fitCanvas();renderViewer();
      logEvent("phase","原生数据已读取，但三维预览不可用","几何尺寸/拓扑将标记为未验证");
    }
    if(info.summary.catia_native){
      const n=info.summary.catia_native;
      logEvent("tool","CATIA V5 原生结构读取成功",
               `${n.bodies?.count??"?"} Body / ${n.parameters?.count??"?"} 参数`);
    }
    $("inspectBtn").disabled=false;$("offlineBtn").disabled=false;setState(
      has3d?"模型已就绪":"原生数据已就绪（几何未验证）","good");
  }catch(e){logEvent("error","模型解析失败",e.message);setState("解析失败");alert("解析失败："+e.message);}
  finally{busy($("uploadBtn"),false);}
});
function getConfig(){
  let o={
    provider:$("provider").value,
    base_url:$("baseUrl").value.trim(),
    model:$("modelName").value.trim(),
    api_key:$("apiKey").value.trim(),
    max_total_tokens:Number($("tokenBudget").value),
    max_rounds:Number($("maxRounds").value),
    max_completion_tokens:Number($("maxOutput").value),
    timeout_sec:Number($("timeout").value),
    token_param:$("tokenParam").value,
    retries:2,max_tools:12
  };
  if($("temperature").value.trim())o.temperature=Number($("temperature").value);
  if(!o.api_key)throw Error("请填写真实 API Key；离线规则检查可无需 API Key 使用。");
  return o;
}
$("testApiBtn").addEventListener("click",async()=>{
  let cfg;try{cfg=getConfig();}catch(e){alert(e.message);return;}
  busy($("testApiBtn"),true,"正在连接...");
  try{
    const data=await getJson("/api/llm/test",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({llm:cfg})});
    alert("连接成功 ✅\n模型回复："+data.answer+"\n报告 Token："+data.usage.total_tokens);
  }catch(e){alert("API 测试失败："+e.message);}
  finally{busy($("testApiBtn"),false);}
});
$("inspectBtn").addEventListener("click",async()=>{
  if(!state.id){alert("请先上传模型");return;}
  let cfg;try{cfg=getConfig();}catch(e){alert(e.message);return;}
  if(state.running)return;
  state.running=true;setState("Agent 检查中","busy");
  $("results").classList.add("hidden");
  $("timeline").replaceChildren();$("inspectBtn").disabled=true;
  logEvent("phase","Agent 已启动","正在通过真实外部 API 请求检查策略");
  try{
    const response=await fetch("/api/inspect/stream",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model_id:state.id,llm:cfg})});
    if(!response.ok)throw Error("请求错误 HTTP "+response.status);
    const reader=response.body.getReader(),decoder=new TextDecoder();
    let carry="", gotReport=false;
    while(true){
      const {done,value}=await reader.read();
      carry+=decoder.decode(value||new Uint8Array(),{stream:!done});
      const lines=carry.split("\n");carry=lines.pop();
      for(const line of lines){
        if(!line.trim())continue;
        const event=JSON.parse(line);
        if(event.kind==="phase")logEvent("phase",event.message);
        else if(event.kind==="tool")logEvent("tool",event.tool.evidence_id+" · "+event.tool.tool,
                                           statusText[event.tool.status]+" · "+event.tool.origin);
        else if(event.kind==="error")logEvent("error",event.message);
        else if(event.kind==="report"){
          gotReport=true;renderReport(event.report);
          setState(event.report.llm_status==="incomplete"?"部分完成":"检查已结束","good");
          logEvent("phase","报告已生成",`动态工具调用 ${event.report.dynamic_tool_call_count} 次`);
        }
      }
      if(done)break;
    }
    if(!gotReport)throw Error("服务器未返回报告");
  }catch(e){logEvent("error","检查出错",e.message);setState("执行出错");}
  finally{state.running=false;$("inspectBtn").disabled=false;}
});
$("offlineBtn").addEventListener("click",async()=>{
  if(!state.id)return;
  try{
    let data=await getJson("/api/offline-checks/"+state.id,{method:"POST"});
    $("timeline").replaceChildren();
    logEvent("phase","仅执行离线固定规则","这不是 LLM Agent 自主检查");
    for(let check of data.checks)logEvent("tool",check.evidence_id+" · "+check.tool,statusText[check.status]);
    $("resultSummary").replaceChildren();
    $("resultSummary").appendChild(makeText("p","离线规则结果：未进行设计意图推理与自适应规划。","offline-note"));
    renderEvidence(data.checks);
    $("aiAnalysis").textContent="离线检查只提供 CAD 工具检测结果，无法替代外部 AI 推理与完整工程验证。";
    $("results").classList.remove("hidden");
    $("exportJson").style.display="none";$("exportHtml").style.display="none";
    $("results").scrollIntoView({behavior:"smooth",block:"start"});
    setState("离线规则完成","good");
  }catch(e){alert(e.message);}
});
function renderEvidence(checks){
  const el=$("evidenceList");el.replaceChildren();
  for(let it of checks){
    const card=makeText("div","","evidence "+it.status);
    const head=makeText("div","","evidence-head");
    head.appendChild(makeText("strong",it.title));
    head.appendChild(makeText("span",it.evidence_id+" · "+statusText[it.status]));
    card.appendChild(head);
    card.appendChild(makeText("p",it.explanation||""));
    if(it.recommendation)card.appendChild(makeText("p","建议："+it.recommendation));
    const details=makeText("details","");details.appendChild(makeText("summary","查看实测数值与工具来源"));
    details.appendChild(makeText("pre",JSON.stringify({tool:it.tool,origin:it.origin,data:it.evidence},null,2)));
    card.appendChild(details);el.appendChild(card);
  }
  if(checks.length===0)el.appendChild(makeText("p","未获得工具检测证据；不可声称已完成 CAD 验证。"));
}
function renderReport(r){
  const cards=[
    ["结构层",structuralText[r.structural_status]||r.structural_status,
      r.structural_status==="fail"?"red":""],
    ["功能层",functionalText[r.functional_status]||r.functional_status,
      r.functional_status.includes("fail")?"red":"amber"],
    ["动态工具调用",r.dynamic_tool_call_count+" 次", ""]
  ];
  $("resultSummary").replaceChildren();
  const row=makeText("div","","summary-row");
  for(const [label,value,color] of cards){const card=makeText("div","","summary-card");
    card.appendChild(makeText("small",label));card.appendChild(makeText("strong",value,color));row.appendChild(card);}
  $("resultSummary").appendChild(row);
  renderEvidence(r.tool_trace);
  let hypothesis=r.preliminary_llm_intent_hypotheses?.join("\n")||"";
  let head=r.llm_status==="incomplete"?("LLM 未完整完成："+r.llm_error+"\n\n"):"";
  $("aiAnalysis").textContent=head+(hypothesis?"初步设计意图（LLM 假设）：\n"+hypothesis+"\n\n":"")
      +(r.ai_analysis_unverified_until_engineer_review||"没有可用的 AI 结论。请检查 API 配置与模型 Tool Calling 支持。")
      +"\n\n【工程边界】\n"+r.limitations.slice(0,4).join("\n");
  $("exportJson").style.display="inline-flex";$("exportHtml").style.display="inline-flex";
  $("exportJson").href="/api/reports/"+state.id+".json";
  $("exportHtml").href="/api/reports/"+state.id+".html";
  $("results").classList.remove("hidden");
  $("results").scrollIntoView({behavior:"smooth",block:"start"});
}

// Dependency-free 3D preview built from the actual OCCT tessellation / Trimesh triangles.
const canvas=$("viewer"), ctx=canvas.getContext("2d");
function fitCanvas(){
  const r=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);
  ctx.setTransform(dpr,0,0,dpr,0,0);
}
function renderViewer(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  ctx.clearRect(0,0,w,h);if(!state.mesh?.faces?.length)return;
  const verts=state.mesh.vertices, faces=state.mesh.faces;
  const len=verts.length;let min=[Infinity,Infinity,Infinity], max=[-Infinity,-Infinity,-Infinity];
  for(const v of verts){for(let j=0;j<3;j++){min[j]=Math.min(min[j],v[j]);max[j]=Math.max(max[j],v[j]);}}
  const center=min.map((m,i)=>(m+max[i])/2);
  const maxDim=Math.max(...max.map((m,i)=>m-min[i]))||1;
  const scale=Math.min(w,h)*.66/maxDim*state.zoom;
  const cy=Math.cos(state.yaw),sy=Math.sin(state.yaw),
        cx=Math.cos(state.pitch),sx=Math.sin(state.pitch);
  const v2=verts.map(v=>{
    const x=v[0]-center[0], y=v[1]-center[1], z=v[2]-center[2];
    const x1=x*cy+z*sy, z1=-x*sy+z*cy;
    return [w*.5+x1*scale,h*.51-(y*cx-z1*sx)*scale, y*sx+z1*cx];
  });
  const tris=[];
  for(const f of faces){
    const a=v2[f[0]],b=v2[f[1]],c=v2[f[2]];
    const ab=[b[0]-a[0],b[1]-a[1],b[2]-a[2]],
          ac=[c[0]-a[0],c[1]-a[1],c[2]-a[2]];
    // Canvas Y points down, Lambert-lite shading for depth without WebGL dependencies.
    const nz=ab[0]*ac[1]-ab[1]*ac[0];
    const facing=Math.abs(nz);
    if(facing<1e-6)continue;
    const depth=(a[2]+b[2]+c[2])/3;
    tris.push({a,b,c,depth,facing});
  }
  tris.sort((a,b)=>a.depth-b.depth);
  const bgHatch=Math.max(28,Math.round(w/14));
  ctx.strokeStyle="rgba(91,139,130,.06)";ctx.lineWidth=1;
  for(let x=0;x<w;x+=bgHatch){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
  for(let y=0;y<h;y+=bgHatch){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  for(const t of tris){
    const fade=Math.min(1,Math.max(0,(t.depth/maxDim)+.65));
    const light=Math.max(37,Math.min(76,49+fade*18));
    ctx.beginPath();ctx.moveTo(t.a[0],t.a[1]);
    ctx.lineTo(t.b[0],t.b[1]);ctx.lineTo(t.c[0],t.c[1]);ctx.closePath();
    ctx.fillStyle=`hsl(177 24% ${light}%)`;ctx.fill();
    ctx.strokeStyle="rgba(24,80,86,.17)";ctx.lineWidth=.55;ctx.stroke();
  }
}
let queued=false;
function queueDraw(){
  if(queued)return;queued=true;
  requestAnimationFrame(()=>{queued=false;renderViewer();});
}
canvas.addEventListener("pointerdown",e=>{
  if(!state.mesh)return;state.drag=true;state.x=e.clientX;state.y=e.clientY;
  canvas.setPointerCapture(e.pointerId);canvas.classList.add("dragging");
});
canvas.addEventListener("pointermove",e=>{
  if(!state.drag)return;
  state.yaw+=(e.clientX-state.x)*.008;state.pitch+=(e.clientY-state.y)*.008;
  state.pitch=Math.max(-1.5,Math.min(1.5,state.pitch));
  state.x=e.clientX;state.y=e.clientY;queueDraw();
});
["pointerup","pointercancel"].forEach(ev=>canvas.addEventListener(ev,()=>{state.drag=false;canvas.classList.remove("dragging");}));
canvas.addEventListener("wheel",e=>{
  if(!state.mesh)return;e.preventDefault();
  state.zoom=Math.min(5,Math.max(.25,state.zoom*(e.deltaY>0?.91:1.10)));queueDraw();
},{passive:false});
window.addEventListener("resize",()=>{fitCanvas();queueDraw();});
fitCanvas();
