const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function publicLink(value) {
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || !url.hostname.includes('.') || /[\s\x00-\x1f]/.test(value)) return null;
    return url.href;
  } catch { return null; }
}
const time = value => Number.isFinite(value) ? new Date(value*1000).toLocaleString('ko-KR', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const link = (url, label) => publicLink(url) ? `<a href="${esc(publicLink(url))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${esc(label)}</a>` : '';
export function companyContent(data) {
  const p=data.profile, news=data.news || {}, available=p&&!p.unavailable;
  const overview=available&&p.overview?`<section class="company-products"><h3>어떤 회사인가요?</h3><p>${esc(p.overview)}</p><div class="company-sources">${link(p.overview_source_url,p.overview_source_label||'기업 소개 출처')}</div><p class="company-date">소개문 확인 ${time(p.overview_checked_at)}${p.overview_unavailable?' · 최신 조회가 어려워 마지막 확인 자료를 표시합니다.':''}</p></section>`:'';
  const profile = available ? `<p class="company-industry">${esc(p.industry || '업종 미확인')}</p>${overview}<section class="company-products"><h3>주요 제품·사업</h3><p>${esc(p.products || '등록된 주요제품 정보가 없습니다.')}</p>${!p.overview?'<p class="company-date">공식 홈페이지 소개문을 확인하지 못해 등록된 기본정보를 표시합니다.</p>':''}</section><div class="company-sources">${link(p.website,'공식 홈페이지')}${link(p.source_url,'기본정보 출처 · KIND')}</div><p class="company-date">기본정보 확인 ${time(p.checked_at)}${data.profile_stale?' · 마지막 확인 자료':''}</p>` : `<p class="company-message">${data.pending?'기업 정보를 확인하고 있습니다.':'등록된 기업 정보를 확인하지 못했습니다.'}</p>`;
  const messages={WAITING:'최신 뉴스를 확인하고 있습니다.',EMPTY:'검색된 관련 뉴스가 없습니다.',ERROR:'뉴스 연결이 지연되었습니다. 잠시 후 다시 확인해 주세요.',LIMIT:'오늘 또는 이번 달의 조회 한도에 도달했습니다.',SETUP_REQUIRED:'뉴스 연결 설정을 확인하고 있습니다.'};
  const items=news.state==='READY' && Array.isArray(news.items) ? news.items.slice(0,3) : [];
  return `<section class="company-profile" aria-label="기업 소개">${profile}</section><section class="company-news" aria-label="관련 뉴스"><div class="company-section-title"><h3>관련 최신 뉴스</h3><span>네이버 검색</span></div>${items.length?`<ol>${items.map(item=>`<li>${link(item.url,item.title)}<div class="news-meta"><span>${esc(item.publisher || '기사 원문')}</span><time>${esc(item.provided_at?new Date(item.provided_at).toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul'}):'시각 미확인')}</time></div></li>`).join('')}</ol>`:`<p class="company-message" role="status">${messages[news.state] || '뉴스를 확인하지 못했습니다.'}</p>`}<p class="company-date">${news.fetched_at?'조회 '+time(news.fetched_at)+' · ':''}최신순 검색 결과 · 날짜는 뉴스 제공일</p></section><p class="company-disclaimer">소개문은 기업 공식 자료, 업종·주요제품은 KIND 등록 정보입니다. 최신 사업구성과 다를 수 있습니다. 뉴스는 매매 조건에 반영하지 않습니다.</p>`;
}

export function installCompanyDetails({load, demo=false}) {
  const dialog=document.querySelector('#company-dialog');
  let generation=0, timer, code;
  function close(){generation++;clearTimeout(timer);if(dialog.open)dialog.close();}
  dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);document.querySelector(`[data-company="${code}"]`)?.focus();});
  dialog.addEventListener('click',event=>{if(event.target.closest('[data-company-close]')||event.target===dialog)close();});
  new MutationObserver(()=>{if(document.querySelector('#login-form'))close();}).observe(document.querySelector('#app'),{childList:true});
  document.querySelector('#app').addEventListener('click',async event=>{
    const button=event.target.closest('[data-company]');
    if(!button)return;
    clearTimeout(timer);const own=++generation;code=button.dataset.company;
    dialog.innerHTML=`<div class="company-panel"><header class="company-header"><div><h2 id="company-heading">${esc(button.dataset.name)}</h2><span>${esc(code)} · 기업 소개</span></div><button class="icon-button" data-company-close aria-label="기업 소개 닫기" title="닫기"><svg width="20" height="20" aria-hidden="true"><use href="icons.svg#x"/></svg></button></header><div class="company-body" aria-live="polite"><p class="company-message">기업·뉴스 정보를 확인하고 있습니다.</p></div></div>`;
    if(!dialog.open)dialog.showModal();
    let checks=0;
    async function refresh(){
      try {
        const result=demo?demoCompany(code,button.dataset.name):await load(code);
        if(own!==generation||!dialog.open)return;
        dialog.querySelector('.company-body').innerHTML=companyContent(result);
        if(result.pending&&++checks<8)timer=setTimeout(refresh,2000);
        else if(result.pending)dialog.querySelector('.company-body').insertAdjacentHTML('afterbegin','<p class="company-message">조회가 지연되고 있습니다. 잠시 후 다시 열어 주세요.</p>');
      }catch{
        if(own===generation&&dialog.open)dialog.querySelector('.company-body').innerHTML='<p class="company-message" role="alert">기업 정보를 불러오지 못했습니다. 가격 갱신과 매매 감시는 계속됩니다.</p>';
      }
    }
    refresh();
  });
}

function demoCompany(code,name){
  return {code,name,pending:false,profile:{name,industry:'예시 업종',overview:'화면 검증용 가상 기업입니다. 산업용 센서와 전자부품을 생산해 기업 고객에게 공급합니다.',overview_source_url:'https://example.com',overview_source_label:'예시 소개 출처',overview_checked_at:Date.now()/1000,products:'예시: 산업용 센서, 전자부품, 유지보수 서비스',website:'https://example.com',source_url:'https://kind.krx.co.kr/',checked_at:Date.now()/1000},news:{state:'READY',fetched_at:Date.now()/1000,items:[{title:'산업용 부품 공급 확대…새로운 생산라인 가동',publisher:'예시 뉴스',url:'https://example.com/news/1',provided_at:new Date().toISOString()},{title:'분기 실적 발표, 주력 사업 현황 공개',publisher:'예시 경제',url:'https://example.com/news/2',provided_at:new Date().toISOString()},{title:'국내외 고객사와 신규 공급 계약 체결',publisher:'예시 산업',url:'https://example.com/news/3',provided_at:new Date().toISOString()}]}};
}
