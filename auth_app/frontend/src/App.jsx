import { useCallback, useEffect, useRef, useState } from 'react';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

/* ─── Attribute labels ──────────────────────── */
const ATTR_LABELS = {
  relationship_type:    'Relationship',
  parties_involved:     'Parties',
  issue_types:          'Issue Type',
  timeline_duration:    'Timeline',
  living_situation:     'Living Situation',
  financial_dependency: 'Financial',
  children_involved:    'Children',
  prior_complaints:     'Prior Complaints',
  evidence_available:   'Evidence',
  relief_sought:        'Relief Sought',
};

const PILL_CLS = {
  'Victim Case Summary':           'pill-summary',
  'Predicted Legal Outcomes':      'pill-outcomes',
  'Expected Duration of the Case': 'pill-duration',
  'Decision Recommendation':       'pill-recommend',
  'Reason for Recommendation':     'pill-reason',
  'Recommended Next Actions':      'pill-actions',
};
const SECTION_ICONS = {
  'Victim Case Summary':           'SUM',
  'Predicted Legal Outcomes':      'OUT',
  'Expected Duration of the Case': 'DUR',
  'Decision Recommendation':       'REC',
  'Reason for Recommendation':     'WHY',
  'Recommended Next Actions':      'ACT',
};

/* ─── SVG Icon Components ───────────────── */
const IconExternal = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
    <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
  </svg>
);
const IconDoc = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
  </svg>
);
const IconScale = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="3" x2="12" y2="21"/>
    <path d="M3 9l9-7 9 7-9-7-9 7"/>
    <path d="M6 18h12"/>
    <polyline points="3 9 9 15 15 9"/>
    <polyline points="9 9 15 15 21 9"/>
  </svg>
);
const IconArrow = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="5" y1="12" x2="19" y2="12"/>
    <polyline points="12 5 19 12 12 19"/>
  </svg>
);

/* Abbreviation badge used as act identifier in lists */
function ActBadge({ abbr, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 34, height: 34, borderRadius: 7, flexShrink: 0,
      background: color, fontSize: 9, fontWeight: 800,
      color: '#fff', letterSpacing: '0.03em', textTransform: 'uppercase',
      fontFamily: 'Inter, sans-serif', lineHeight: 1.1, textAlign: 'center',
      padding: '2px 3px', wordBreak: 'break-word',
    }}>{abbr}</span>
  );
}

/* ─── Legal library (rich data + gov links, no emoji) ─── */
const LEGAL_LIBRARY = [
  { id:'pwdva',      abbr:'PWDVA',  color:'#2563eb', title:'Protection of Women from Domestic Violence Act, 2005',  sub:'PWDVA — Civil Remedy',           year:'2005',               sections:'37 Sections', tags:[{l:'Civil Law',c:'blue'},{l:'Applicable',c:'green'}],   desc:'Provides protection orders, residence orders, monetary relief and custody orders to victims of domestic violence including physical, verbal, emotional, economic and sexual abuse.', keySections:['§12 — Application to Magistrate','§18 — Protection Orders','§19 — Residence Orders','§20 — Monetary Relief','§21 — Custody Orders'], howToUse:'File application (Form I) under §12 before the Magistrate. A Domestic Violence Protection Officer (DVPO) can assist you file for free. Interim relief is grantable on the same day.', links:[{label:'Read Full Act — WCD Ministry',url:'https://wcd.nic.in/sites/default/files/wcd_domestic-violence.pdf'},{label:'NCW — File Complaint Online',url:'https://ncwapps.nic.in/frmComplaint.aspx'},{label:'One Stop Centre Scheme',url:'https://wcd.nic.in/schemes2014/one-stop-centre-scheme'}]},
  { id:'ipc498a',    abbr:'498A',   color:'#dc2626', title:'IPC §498A / BNS §85 — Cruelty by Husband or Relatives',    sub:'Indian Penal Code / BNS 2023',   year:'1860 / 2023',        sections:'§498A',      tags:[{l:'Criminal Law',c:'red'},{l:'Cognizable',c:'amber'}],    desc:'Criminally punishes husband or relatives for cruelty — physical or mental — including harassment for dowry. Imprisonment up to 3 years and fine.', keySections:['§498A — Cruelty (IPC)','§85 — Cruelty (BNS 2023)','Cognizable: FIR without warrant','Non-bailable: No automatic bail'], howToUse:'File an FIR at the nearest police station. If police refuses, file a complaint before a Magistrate under §190 CrPC. The crime is non-bailable so accused can be arrested immediately.', links:[{label:'Read §498A — IndianKanoon',url:'https://indiankanoon.org/doc/538436/'},{label:'eCourts — Track your Case',url:'https://services.ecourts.gov.in/'},{label:'Bharatiya Nyaya Sanhita, BNS 2023',url:'https://www.indiacode.nic.in/handle/123456789/20062'}]},
  { id:'crpc125',    abbr:'CrPC',   color:'#059669', title:'Section 125 CrPC — Maintenance of Wives & Children',         sub:'Code of Criminal Procedure',     year:'1973',               sections:'§125–128',  tags:[{l:'Maintenance',c:'green'},{l:'Fast Track',c:'blue'}],     desc:'Allows wife to claim monthly maintenance from husband if unable to maintain herself. Interim maintenance grantable within 60 days. No court fee required.', keySections:['§125 — Order for maintenance','§126 — Jurisdiction of court','§127 — Alteration in allowance','§128 — Enforcement by warrant'], howToUse:'File petition in Family Court or Magistrate court. Attach income proof of husband and your monthly expense details. Interim maintenance is typically granted within 60 days. Free legal aid is available at DLSA.', links:[{label:'Read §125 CrPC — IndianKanoon',url:'https://indiankanoon.org/doc/195908/'},{label:'NALSA — Free Legal Aid',url:'https://nalsa.gov.in/'},{label:'eCourts Family Court Locator',url:'https://districts.ecourts.gov.in/'}]},
  { id:'dowry',      abbr:'DPA',    color:'#7c3aed', title:'Dowry Prohibition Act, 1961',                              sub:'Anti-Dowry Law',                 year:'1961',               sections:'§3,§4,§6',   tags:[{l:'Criminal Law',c:'red'},{l:'Anti-Dowry',c:'amber'}],     desc:'Makes giving or taking dowry a criminal offence. Minimum 5 years imprisonment and fine of Rs.15,000 or value of dowry. Covers demand before, at or after marriage.', keySections:['§3 — Penalty for giving or taking dowry','§4 — Penalty for demanding dowry','§6 — Return of dowry to woman','§8B — Dowry Prohibition Officers'], howToUse:'Register a complaint with the Dowry Prohibition Officer in your district collector office, or file an FIR at the nearest police station. NCW can also be approached directly.', links:[{label:'Read Full Act — IndianKanoon',url:'https://indiankanoon.org/doc/1007566/'},{label:'NCW — Complaint Portal',url:'https://ncwapps.nic.in/frmComplaint.aspx'},{label:'Ministry of Women & Child Dev',url:'https://wcd.nic.in/'}]},
  { id:'succession', abbr:'HSA',    color:'#b45309', title:"Hindu Succession Act — Women's Inheritance Rights",         sub:'Property & Inheritance Law',     year:'1956 (amended 2005)', sections:'§6,§14',     tags:[{l:'Property',c:'amber'},{l:'Inheritance',c:'blue'}],       desc:"Grants daughters equal rights to ancestral property as sons (post 2005 amendment). Married daughters retain this right. Applicable to Hindu, Buddhist, Jain, Sikh families.", keySections:['§6 — Devolution of interest (amended 2005)','§14 — Property of female Hindu','§15 — General rules of succession','§16 — Order of succession'], howToUse:'File a civil suit in the District Court for partition or declaration of share in ancestral property. Also approach the Tahsildar or Revenue Officer for ancestral property mutation records.', links:[{label:'Read Full Act — India Code',url:'https://www.indiacode.nic.in/handle/123456789/2189'},{label:'Department of Justice',url:'https://doj.gov.in/'},{label:'NALSA — Legal Aid & Advice',url:'https://nalsa.gov.in/'}]},
  { id:'custody',    abbr:'HMG',    color:'#0891b2', title:'Hindu Minority & Guardianship Act — Child Custody',        sub:'Family & Child Law',             year:'1956',               sections:'§6,§13',     tags:[{l:'Child Custody',c:'green'},{l:'Family Law',c:'blue'}],   desc:"Mother is natural guardian of children below 5 years. Courts always prioritize welfare of child. Father's rights are not absolute; child's welfare is the paramount consideration.", keySections:['§6 — Natural guardians of Hindu minor','§13 — Welfare of minor is paramount','§7 — Guardianship in matters of adoption','PWDVA §21 — Temporary Custody (emergency)'], howToUse:"File a Guardianship petition in the Family Court. For emergency custody, apply under PWDVA §26. Protection Officers can assist at no cost. Many states waive court fees for women petitioners.", links:[{label:'Read HMGA — IndianKanoon',url:'https://indiankanoon.org/doc/1099021/'},{label:'eCourts — Family Court Locator',url:'https://districts.ecourts.gov.in/'},{label:'WCD — Child & Women Welfare',url:'https://wcd.nic.in/'}]},
  { id:'it',         abbr:'ITA',    color:'#dc2626', title:'Information Technology Act — Cyber Crimes Against Women',  sub:'IT Act 2000 / BNS 2023',         year:'2000',               sections:'§66E,§67',   tags:[{l:'Cyber Crime',c:'red'},{l:'Digital Safety',c:'blue'}],  desc:'Covers digital stalking, online harassment, morphing, non-consensual sharing of intimate images, cyberstalking, and sextortion. BNS 2023 adds stronger provisions.', keySections:['§66E — Violation of privacy (images)','§67 — Publication of obscene material','§67A — Sexually explicit material','BNS §77 — Stalking (digital or physical)','BNS §79 — Voyeurism'], howToUse:'Report online at the National Cyber Crime Reporting Portal (cybercrime.gov.in). Reports can be made anonymously. Also file FIR at the local Cyber Cell or nearest police station.', links:[{label:'National Cyber Crime Portal (Govt)',url:'https://cybercrime.gov.in/'},{label:'Read IT Act — India Code',url:'https://www.indiacode.nic.in/bitstream/123456789/1999/3/A2000-21.pdf'},{label:'NCW — Online Complaint',url:'https://ncwapps.nic.in/frmComplaint.aspx'}]},
  { id:'posh',       abbr:'POSH',   color:'#2563eb', title:'POSH Act — Prevention of Sexual Harassment at Workplace',  sub:'POSH Act, 2013',                 year:'2013',               sections:'§2,§4,§9',   tags:[{l:'Workplace',c:'blue'},{l:'Sexual Harassment',c:'red'}], desc:'Every organization with 10+ employees must constitute an Internal Complaints Committee (ICC). Covers all forms of sexual harassment at workplace, on work trips, and in online work settings.', keySections:['§4 — Constitution of Internal Complaints Committee','§9 — Complaint filing (within 90 days)','§11 — Inquiry procedure of ICC','§13 — Recommended action after ICC report'], howToUse:"File complaint with your organization's ICC within 90 days. If no ICC exists, approach the Local Complaints Committee (LCC) at the District level. Register complaint on SHe-Box portal.", links:[{label:'SHe-Box — Official Govt Portal',url:'https://shebox.nic.in/'},{label:'Read POSH Act — IndianKanoon',url:'https://indiankanoon.org/doc/56539849/'},{label:'NCW — POSH Complaint',url:'https://ncwapps.nic.in/frmComplaint.aspx'}]},
  { id:'crpa',       abbr:'CRPA',   color:'#0891b2', title:'Code of Criminal Procedure — Bail, FIR & Trial Rights',   sub:'CrPC 1973 / BNSS 2023',          year:'1973 / 2023',        sections:'§154,§437',  tags:[{l:'Procedure',c:'blue'},{l:'FIR & Bail',c:'amber'}],       desc:'Governs how FIRs are filed, bail is given or denied, trials are conducted, and how victims can approach courts directly. BNSS 2023 replaced CrPC with updated provisions.', keySections:['§154 — Information in cognizable offence (FIR)','§156(3) — Magistrate-ordered investigation','§437 — Bail in non-bailable offences','§439 — Special powers of Sessions Court for bail'], howToUse:'File FIR at nearest police station. If refused, approach Superintendent of Police (SP) or file private complaint before Magistrate under §156(3) or §200 CrPC.', links:[{label:'Read CrPC — IndianKanoon',url:'https://indiankanoon.org/doc/1308537/'},{label:'eCourts Case Status Portal',url:'https://services.ecourts.gov.in/'},{label:'BNSS 2023 — India Code',url:'https://www.indiacode.nic.in/handle/123456789/20062'}]},
  { id:'ioa',        abbr:'HPS',    color:'#059669', title:'Hindu Marriage Act — Divorce, Alimony & Restitution',      sub:'Hindu Personal & Family Law',    year:'1955',               sections:'§13,§24,§25', tags:[{l:'Divorce',c:'amber'},{l:'Alimony',c:'green'}],           desc:'Governs Hindu marriage, grounds for divorce, interim alimony during proceedings, permanent alimony after divorce, and restitution of conjugal rights.', keySections:['§13 — Grounds for divorce','§13B — Divorce by mutual consent','§24 — Maintenance pendente lite (during case)','§25 — Permanent alimony and maintenance'], howToUse:'File a petition for divorce in the Family Court of the district where you last resided together. You can apply for interim maintenance under §24 immediately after filing.', links:[{label:'Read Hindu Marriage Act — IndianKanoon',url:'https://indiankanoon.org/doc/550624/'},{label:'eCourts — Family Court Locator',url:'https://districts.ecourts.gov.in/'},{label:'NALSA — Free Legal Aid',url:'https://nalsa.gov.in/'}]},
];

/* ─── My Documents (no emoji icons) ───────────── */
const MY_DOCUMENTS = [
  { id:'intake',      abbr:'AI',    color:'#2563eb', title:'Case Intake Summary',                    meta:'AI Generated · Today',           tags:[{l:'AI Generated',c:'blue'},{l:'Current Case',c:'green'}],  desc:'AI-generated summary of your case including key facts, timeline, parties involved, and identified legal issues.', content:'This document is auto-generated after your NyayaSakhi consultation. Start a conversation to build your case intake summary with all collected facts.', links:[{label:'NCW — Online Legal Consultation',url:'https://ncwapps.nic.in/frmComplaint.aspx'},{label:'NALSA — Free Legal Aid',url:'https://nalsa.gov.in/'},{label:'Legal Services India',url:'http://www.legalservicesindia.com/'}]},
  { id:'laws',        abbr:'LAW',   color:'#7c3aed', title:'Applicable Laws Report',                 meta:'AI Generated · Today',           tags:[{l:'Legal Analysis',c:'blue'},{l:'10 Acts',c:'amber'}],      desc:'List of Indian laws, IPC sections and court precedents applicable to your specific situation based on the facts you shared.', content:'Complete a consultation first. Based on your case, NyayaSakhi identifies relevant Indian acts, key sections, and applicable precedents from eCourts judgements.', links:[{label:'IndianKanoon — Case Law Search',url:'https://indiankanoon.org/'},{label:'India Code — Official Legislation',url:'https://www.indiacode.nic.in/'},{label:'Department of Justice, India',url:'https://doj.gov.in/'}]},
  { id:'protection',  abbr:'FORM',  color:'#059669', title:'Protection Order Application — Form I',  meta:'Template · PWDVA 2005',          tags:[{l:'Downloadable',c:'green'},{l:'PWDVA',c:'blue'}],          desc:'Official Form I for applying for a Protection Order before the Magistrate under Protection of Women from Domestic Violence Act 2005.', content:'Form I is filed under Section 12 of PWDVA 2005 to seek Protection Order, Residence Order, and Monetary Relief. Part A: Your details. Part B: Respondent details. Submit through a Protection Officer or directly at the Magistrate court.', links:[{label:'Download Form I — WCD Ministry (PDF)',url:'https://wcd.nic.in/sites/default/files/wcd_domestic-violence.pdf'},{label:'eCourts — Locate Magistrate Court',url:'https://districts.ecourts.gov.in/'},{label:'WCD — Protection Officers Directory',url:'https://wcd.nic.in/'}]},
  { id:'checklist',   abbr:'LIST',  color:'#b45309', title:'Evidence Checklist',                       meta:'Template · Best Practices',      tags:[{l:'Checklist',c:'amber'},{l:'Evidence',c:'red'}],           desc:'Checklist of evidence types to gather — medical reports, messages, photographs, witnesses, financial records.', content:'Strong evidence significantly improves your case. Collect: (1) Medical injury reports from government hospital (2) Screenshot and backup of abusive messages (3) Photographs of injuries or damaged property (4) Witness names and contact numbers (5) Bank statements showing financial control (6) Audio or video recordings where legal (7) Documents showing husband income and property.', links:[{label:'National Cyber Crime Portal — Evidence',url:'https://cybercrime.gov.in/'},{label:'NALSA — Legal Aid Authority',url:'https://nalsa.gov.in/'},{label:'NCW — Women Helpline Support',url:'https://ncw.nic.in/'}]},
  { id:'maintenance', abbr:'CrPC',  color:'#0891b2', title:'Maintenance Claim Guide — Section 125 CrPC', meta:'Guide · Legal Process',          tags:[{l:'Step-by-Step',c:'green'},{l:'Maintenance',c:'blue'}],   desc:'Step-by-step guide to filing a maintenance application in Magistrate court including forms, procedure, and timelines.', content:'Step 1: File petition in Family Court or Magistrate court using Form II. Step 2: Attach income proof of husband (salary slip, ITR, bank statement). Step 3: Submit your monthly expense statement. Step 4: Court may grant interim maintenance within 60 days of filing. Step 5: Final maintenance order is passed after full hearing. No court fees are required. Free legal aid is available at your District Legal Services Authority (DLSA).', links:[{label:'NALSA — Free Legal Aid Authority',url:'https://nalsa.gov.in/'},{label:'District Legal Services Locator',url:'https://nalsa.gov.in/lsams/'},{label:'Read Section 125 CrPC — IndianKanoon',url:'https://indiankanoon.org/doc/195908/'}]},
  { id:'helplines',   abbr:'HELP',  color:'#dc2626', title:'Emergency Helplines & Contacts',           meta:'Resource · Always Updated',      tags:[{l:'Emergency',c:'red'},{l:'Helplines',c:'amber'}],          desc:'National and state-wise women helplines, legal aid contacts, shelter homes, and specialist police contacts.', content:'EMERGENCY CONTACTS:\n\nWomen Helpline: 181\nNational Emergency (Police / Fire / Medical): 112\nNCW Helpline: 7827170170\nNational Cyber Crime (Online): 1930\nChild Helpline: 1098\niCall Mental Health (TISS): 9152987821\nVanitha Helpline (South India): 1091\n\nALL calls to 181 are FREE, 24x7, and available in all states.', links:[{label:'NCW — National Commission for Women',url:'https://ncw.nic.in/'},{label:'One Stop Centre — WCD Ministry',url:'https://wcd.nic.in/schemes2014/one-stop-centre-scheme'},{label:'NALSA — Legal Aid Locator',url:'https://nalsa.gov.in/'}]},
];

/* ─── Build action tags from analysis ────────── */
function buildActionTags(fr) {
  if (!fr) return [];
  const tags = [];
  const t = Object.values(fr).join(' ');
  if (/protection order|PWDVA/i.test(t))     tags.push({ label: 'Protection Order Available', cls: 'tag-green' });
  if (/maintenance|alimony|125/i.test(t))    tags.push({ label: 'Maintenance Claim', cls: 'tag-blue' });
  if (/evidence.*weak|no evidence/i.test(t)) tags.push({ label: 'Evidence Gaps Found', cls: 'tag-red' });
  if (/498A|FIR|criminal/i.test(t))          tags.push({ label: 'Criminal FIR Possible', cls: 'tag-amber' });
  if (/urgent|immediate/i.test(t))           tags.push({ label: 'Seek Urgent Help', cls: 'tag-red' });
  if (/residence order/i.test(t))            tags.push({ label: 'Residence Order', cls: 'tag-blue' });
  if (tags.length === 0) tags.push({ label: 'Legal Options Available', cls: 'tag-green' });
  return tags;
}

/* ─── Build accordion source sections ────────── */
function buildAccordionSections(fr) {
  if (!fr) return [];
  const text = Object.values(fr).join(' ');
  const sections = [];

  // Legal issues (amber)
  const issues = [];
  if (/PWDVA|domestic violence/i.test(text))   issues.push({ title: 'PWDVA 2005 — Protection Order', body: 'You may be entitled to a Protection Order, Residence Order, and/or Monetary Relief under the PWDVA 2005. This is a strong civil remedy with fast redressal.', type: 'issue' });
  if (/498A|cruelty/i.test(text))              issues.push({ title: 'IPC §498A — Cruelty', body: 'The conduct described may constitute cruelty under IPC §498A / BNS §85. This is a cognizable and non-bailable offence.', type: 'issue' });
  if (/maintenance/i.test(text))               issues.push({ title: '§125 CrPC — Maintenance Right', body: 'You may claim monthly maintenance under §125 CrPC. No maximum limit — courts decide based on husband\'s income and lifestyle.', type: 'issue' });
  if (issues.length) sections.push({ label: `Legal Issues Found: ${issues.length}`, countCls: 'issues', cards: issues });

  // Evidence gaps (red)
  const gaps = [];
  if (/no evidence|no witness|no medical/i.test(text)) gaps.push({ title: 'Insufficient Evidence', body: 'The case mentions limited evidence. Strengthen your case by collecting WhatsApp messages, photographs, medical reports, and witness statements.', type: 'gap' });
  if (/contested|oppose|reject/i.test(text))  gaps.push({ title: 'Contested Outcome Risk', body: 'The opposite party may contest aggressively. Document all incidents with dates, times, and details. Keep records of all communications.', type: 'gap' });
  if (gaps.length) sections.push({ label: `Evidence Gaps: ${gaps.length}`, countCls: 'gaps', cards: gaps });

  // Legal sources (blue)
  const laws = [];
  if (/PWDVA/i.test(text)) laws.push({ title: 'Protection of Women from Domestic Violence Act, 2005', body: '§12 — Application to Magistrate. §18 — Protection Orders. §19 — Residence Orders. §20 — Monetary Relief. All can be applied simultaneously.', type: 'law' });
  if (/498A|BNS 85/i.test(text)) laws.push({ title: 'IPC §498A / BNS §85', body: 'Cognizable, non-bailable, compoundable only with court permission. FIR can be filed at any police station. Arrest can be made without warrant.', type: 'law' });
  if (/maintenance|Section 125/i.test(text)) laws.push({ title: '§125 CrPC — Maintenance', body: 'Jurisdiction: Magistrate court. Interim maintenance can be ordered within 60 days. Can be enforced by warrant if not paid.', type: 'law' });
  if (laws.length) sections.push({ label: `Legal Sources: ${laws.length}`, countCls: 'sources', cards: laws });

  return sections;
}

/* ─── Build citation cards from analysis ─────── */
function buildCitations(fr) {
  if (!fr) return [];
  const text = Object.values(fr).join(' ');
  const cits = [];
  if (/PWDVA|domestic violence/i.test(text))
    cits.push({ icon: '⚖️', title: 'PWDVA 2005 — Protection Orders', sub: 'Statute · Parliament of India · 2005', col1: { label: 'Type', val: 'Civil Statute' }, col2: { label: 'Remedy', val: 'Protection Order' }, col3: { label: 'Court', val: 'Magistrate' } });
  if (/498A|cruelty/i.test(text))
    cits.push({ icon: '🔴', title: 'IPC §498A — Cruelty', sub: 'Criminal Law · Indian Penal Code · 1860', col1: { label: 'Type', val: 'Criminal' }, col2: { label: 'Penalty', val: '3 yrs + fine' }, col3: { label: 'Bail', val: 'Non-bailable' } });
  if (/maintenance|Section 125/i.test(text))
    cits.push({ icon: '💰', title: '§125 CrPC — Maintenance', sub: 'Procedural Law · CrPC · 1973', col1: { label: 'Type', val: 'Civil Claim' }, col2: { label: 'Court', val: 'Magistrate' }, col3: { label: 'Timeline', val: '1–3 months' } });
  return cits;
}

/* ─── Markdown renderer ───────────────────────── */
function md(text) {
  if (!text) return '';
  let h = text
    .replace(/^### (.+)$/gm,   '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,    '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,     '<em>$1</em>')
    .replace(/^[-•]\s+(.+)$/gm,'<li>$1</li>')
    .replace(/^\d+\.\s+(.+)$/gm,'<li>$1</li>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g,   '<br />');
  h = h.replace(/(<li>.*?<\/li>(?:\s*<br \/>)*)+/gs, m => `<ul>${m.replace(/<br \/>/g,'')}</ul>`);
  return `<p>${h}</p>`;
}

/* ─── Accordion section (sources panel) ──────── */
function AccSection({ section }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="acc-section">
      <div className="acc-header" onClick={() => setOpen(p => !p)}>
        <div className="acc-header-left">
          <span className={`acc-count ${section.countCls}`}>{section.cards.length}</span>
          <span className="acc-header-title">{section.label}</span>
        </div>
        <span className={`acc-chevron${open ? ' open' : ''}`}>▼</span>
      </div>
      {open && (
        <div className="acc-body">
          {section.cards.map((card, i) => (
            <div key={i} className={`src-highlight-card ${card.type}`}>
              <div className="src-hc-hdr">
                <span className="src-hc-hdr-title">{card.title}</span>
                <button className="src-resolve-btn">Learn more</button>
              </div>
              <div className="src-hc-body">{card.body}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── My Documents tab ── Two-panel layout ────── */
function MyDocumentsTab({ switchToLibrary }) {
  const [selected, setSelected] = useState(MY_DOCUMENTS[0]);
  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', height: '100%' }}>
      {/* Left list */}
      <div style={{ width: 260, flexShrink: 0, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', background: 'var(--bg-sidebar)', overflow: 'hidden' }}>
        <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>My Documents</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Templates, guides &amp; resources</div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {MY_DOCUMENTS.map(doc => (
            <div key={doc.id} onClick={() => setSelected(doc)} style={{ padding: '10px 14px', cursor: 'pointer', borderBottom: '1px solid rgba(0,0,0,0.04)', background: selected?.id === doc.id ? 'var(--bg-white)' : 'transparent', transition: 'background 0.12s' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 3 }}>
                <ActBadge abbr={doc.abbr} color={doc.color} />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3 }}>{doc.title}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', paddingLeft: 43 }}>{doc.meta}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px', background: 'var(--bg)' }}>
        {selected && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
              <ActBadge abbr={selected.abbr} color={selected.color} />
              <div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em' }}>{selected.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{selected.meta}</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
              {selected.tags.map((t, i) => <span key={i} className={`dtag ${t.c}`}>{t.l}</span>)}
            </div>

            <div style={{ background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px', marginBottom: 16, boxShadow: 'var(--shadow-xs)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 10 }}>About this document</div>
              <div style={{ fontSize: 13.5, color: 'var(--text-mid)', lineHeight: 1.65, whiteSpace: 'pre-line' }}>{selected.content}</div>
            </div>

            <div style={{ background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', boxShadow: 'var(--shadow-xs)' }}>
              <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>Official Government Links &amp; References</div>
              {selected.links.map((lnk, i) => (
                <a key={i} href={lnk.url} target="_blank" rel="noopener noreferrer"
                  style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 18px', borderBottom: i < selected.links.length - 1 ? '1px solid var(--border)' : 'none', textDecoration: 'none', transition: 'background 0.12s', color: 'inherit' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--tag-blue)'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}>
                  <div style={{ width: 32, height: 32, borderRadius: 7, background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: 'var(--text-muted)' }}><IconDoc /></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{lnk.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{new URL(lnk.url).hostname}</div>
                  </div>
                  <span style={{ color: 'var(--tag-blue-txt)', display: 'flex', alignItems: 'center', gap: 3, fontSize: 11, fontWeight: 600 }}><IconExternal /> Open</span>
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ─── Legal Library tab ── Two-panel layout ────── */
function LegalLibraryTab() {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(LEGAL_LIBRARY[0]);
  const filtered = LEGAL_LIBRARY.filter(l =>
    !query || l.title.toLowerCase().includes(query.toLowerCase()) || l.desc.toLowerCase().includes(query.toLowerCase())
  );
  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', height: '100%' }}>
      {/* Left list */}
      <div style={{ width: 290, flexShrink: 0, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', background: 'var(--bg-sidebar)', overflow: 'hidden' }}>
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>Legal Library</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 10px' }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--text-muted)', flexShrink: 0 }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input type="text" placeholder="Search acts, sections…" value={query} onChange={e => setQuery(e.target.value)}
              style={{ flex: 1, border: 'none', background: 'transparent', outline: 'none', fontSize: 12.5, fontFamily: 'inherit', color: 'var(--text)' }} />
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filtered.map(law => (
            <div key={law.id} onClick={() => setSelected(law)}
              style={{ padding: '10px 14px', cursor: 'pointer', borderBottom: '1px solid rgba(0,0,0,0.04)', background: selected?.id === law.id ? 'var(--bg-white)' : 'transparent', transition: 'background 0.12s' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 3 }}>
                <ActBadge abbr={law.abbr} color={law.color} />
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', lineHeight: 1.3 }}>{law.title.length > 42 ? law.title.slice(0, 42) + '…' : law.title}</span>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)', paddingLeft: 43 }}>{law.sub} · {law.year}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right detail */}
      {selected && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px', background: 'var(--bg)' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
            <ActBadge abbr={selected.abbr} color={selected.color} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em', marginBottom: 3 }}>{selected.title}</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>{selected.sub} &nbsp;&middot;&nbsp; {selected.year} &nbsp;&middot;&nbsp; {selected.sections}</div>
            </div>
            <span className="law-badge">Relevant</span>
          </div>

          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
            {selected.tags.map((t, i) => <span key={i} className={`dtag ${t.c}`}>{t.l}</span>)}
          </div>

          {/* Description */}
          <div style={{ background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 12, padding: '16px 20px', marginBottom: 12, boxShadow: 'var(--shadow-xs)' }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 8 }}>About this Act</div>
            <div style={{ fontSize: 13.5, color: 'var(--text-mid)', lineHeight: 1.7 }}>{selected.desc}</div>
          </div>

          {/* Key Sections */}
          <div style={{ background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden', marginBottom: 12, boxShadow: 'var(--shadow-xs)' }}>
            <div style={{ padding: '10px 18px', borderBottom: '1px solid var(--border)', background: 'var(--card-yellow)', fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#92400e' }}>Key Sections</div>
            {selected.keySections.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '9px 18px', borderBottom: i < selected.keySections.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, marginTop: 1, flexShrink: 0 }}>&sect;</span>
                <span style={{ fontSize: 13, color: 'var(--text-mid)', lineHeight: 1.5 }}>{s}</span>
              </div>
            ))}
          </div>

          {/* How to use */}
          <div style={{ background: 'var(--card-teal)', border: '1px solid rgba(16,185,129,0.25)', borderRadius: 12, padding: '14px 18px', marginBottom: 12, boxShadow: 'var(--shadow-xs)' }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#065f46', marginBottom: 7 }}>How to use this law</div>
            <div style={{ fontSize: 13, color: '#064e3b', lineHeight: 1.65 }}>{selected.howToUse}</div>
          </div>

          {/* Official Gov links */}
          <div style={{ background: 'var(--bg-white)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden', boxShadow: 'var(--shadow-xs)' }}>
            <div style={{ padding: '10px 18px', borderBottom: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>Official Government References</div>
            {selected.links.map((lnk, i) => (
              <a key={i} href={lnk.url} target="_blank" rel="noopener noreferrer"
                style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 18px', borderBottom: i < selected.links.length - 1 ? '1px solid var(--border)' : 'none', textDecoration: 'none', transition: 'background 0.12s', color: 'inherit' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--tag-blue)'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                <div style={{ width: 32, height: 32, borderRadius: 7, background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: 'var(--text-muted)' }}><IconDoc /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{lnk.label}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{new URL(lnk.url).hostname}</div>
                </div>
                <span style={{ fontSize: 13, color: 'var(--tag-blue-txt)', fontWeight: 600 }}>↗ Open</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════
   MAIN APP
═══════════════════════════════════════════════ */
export default function App() {
  const [sessionId]      = useState(() => `s-${Date.now()}-${Math.random().toString(36).slice(2,5)}`);
  const [messages,       setMessages]       = useState([]);
  const [inputText,      setInputText]      = useState('');
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState('');
  const [phase,          setPhase]          = useState('gathering');
  const [completeness,   setCompleteness]   = useState(0);
  const [resolvedAttrs,  setResolvedAttrs]  = useState({});
  const [exchangeCount,  setExchangeCount]  = useState(0);
  const [sidebarOpen,    setSidebarOpen]    = useState(false);
  const [sourcesOpen,    setSourcesOpen]    = useState(false);
  const [accSections,    setAccSections]    = useState([]);
  const [activeTab,      setActiveTab]      = useState('Conversations');

  const chatEndRef  = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, loading]);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px'; }
  }, []);

  async function send(text) {
    if (!text.trim() || loading) return;
    if (activeTab !== 'Conversations') setActiveTab('Conversations');
    setMessages(prev => [...prev, { id: `u-${Date.now()}`, role: 'user', content: text.trim() }]);
    setInputText('');
    setLoading(true);
    setError('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    try {
      const res = await fetch(`${API_BASE}/chat/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text.trim() }),
      });
      if (!res.ok) throw new Error(await res.text() || `Error ${res.status}`);
      const data = await res.json();

      setPhase(data.phase || 'gathering');
      setCompleteness((data.completeness || 0) * 100);
      setResolvedAttrs(data.resolved_attributes || {});
      setExchangeCount(data.exchange_count || 0);

      const actionTags = data.is_final ? buildActionTags(data.final_response) : [];
      const citations  = data.is_final ? buildCitations(data.final_response)  : [];
      const sections   = data.is_final ? buildAccordionSections(data.final_response) : [];

      setMessages(prev => [...prev, {
        id: `b-${Date.now()}`,
        role: 'bot',
        content: data.response,
        isFinal: data.is_final,
        finalResponse: data.final_response,
        actionTags,
        citations,
      }]);

      if (data.is_final && sections.length) {
        setAccSections(sections);
        setSourcesOpen(true);
      }
    } catch (e) {
      setError(e.message || 'Something went wrong.');
      setMessages(prev => [...prev, { id: `err-${Date.now()}`, role: 'bot', content: 'I had trouble processing that. Please try again.', actionTags: [], citations: [] }]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(inputText); }
  }

  function resetChat() {
    setMessages([]); setPhase('gathering'); setCompleteness(0);
    setResolvedAttrs({}); setExchangeCount(0); setError('');
    setSourcesOpen(false); setAccSections([]);
    setActiveTab('Conversations');
    fetch(`${API_BASE}/chat/reset/${sessionId}`, { method: 'POST' }).catch(() => {});
    setSidebarOpen(false);
  }

  const showWelcome = messages.length === 0;
  const resolvedList = Object.entries(ATTR_LABELS).filter(([k]) => resolvedAttrs[k]).map(([, label]) => label);

  return (
    <div className="app-shell">

      {/* ── Sidebar ───────────────────────────── */}
      <aside className={`app-sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="sidebar-top">
          <div className="sidebar-brand">
            <img src="/bot-logo.jpeg" alt="NyayaSakhi" />
            <span className="sidebar-brand-name">NyayaSakhi</span>
          </div>
          <button className="new-conv-btn" onClick={resetChat}>+ New conversation</button>
        </div>

        <div className="sidebar-search">
          <span className="sidebar-search-icon">🔍</span>
          <input type="text" placeholder="Search conversations…" />
        </div>

        <p className="sidebar-section-label">All conversations</p>

        <div className="sidebar-conversations">
          {/* Active conversation with fact list */}
          <div className="conv-item active" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0 0 6px' }}>
              <div className="conv-item-body">
                <div className="conv-item-title">{showWelcome ? 'New consultation' : phase === 'gathering' ? 'Intake in progress' : 'Analysis complete'}</div>
                <div className="conv-item-sub">{showWelcome ? 'Active' : `${Math.round(completeness)}% · Active`}</div>
              </div>
              <button className="conv-item-dots">⋯</button>
            </div>
            {/* Sidebar fact items */}
            {resolvedList.length > 0 && (
              <div className="sidebar-fact-list">
                {Object.entries(ATTR_LABELS).filter(([k]) => resolvedAttrs[k]).map(([k, label]) => (
                  <div key={k} className="sidebar-fact-item">
                    <span className="sidebar-fact-icon">✓</span>
                    <div><span className="sidebar-fact-label">{label}</span><span className="sidebar-fact-val">Collected</span></div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Past conversations */}
          {[
            { title: 'Domestic violence intake',   sub: 'Analysis complete · Earlier today' },
            { title: 'Maintenance & alimony query', sub: 'Gathering info · Yesterday' },
            { title: 'Dowry harassment case',       sub: 'Complete · 2 days ago' },
          ].map((c, i) => (
            <div key={i} className="conv-item">
              <div className="conv-item-body">
                <div className="conv-item-title">{c.title}</div>
                <div className="conv-item-sub">{c.sub}</div>
              </div>
              <button className="conv-item-dots">⋯</button>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">🔒 Confidential &amp; Secure AI</div>
      </aside>

      {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}

      {/* ── Main ──────────────────────────────── */}
      <main className="app-main">

        {/* Top nav — 3 tabs, no Live consultants */}
        <nav className="top-nav no-print">
          <div className="top-nav-left">
            <button className="menu-btn-nav" onClick={() => setSidebarOpen(p => !p)}>☰</button>
          </div>
          <div className="top-nav-center">
            {['Conversations', 'My documents', 'Legal library'].map(t => (
              <button
                key={t}
                className={`nav-tab${activeTab === t ? ' active' : ''}`}
                onClick={() => setActiveTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="top-nav-right">
            {accSections.length > 0 && activeTab === 'Conversations' && (
              <button
                className={`nav-source-btn${sourcesOpen ? ' open' : ''}`}
                onClick={() => setSourcesOpen(p => !p)}
              >
                📚 {sourcesOpen ? 'Hide Sources' : `Sources (${accSections.reduce((a,s)=>a+s.cards.length,0)})`}
              </button>
            )}
            {messages.length >= 2 && (
              <button className="nav-export-btn no-print" onClick={() => window.print()}>↓ Export PDF</button>
            )}
            <div className="nav-avatar"><img src="/bot-logo.jpeg" alt="avatar" /></div>
          </div>
        </nav>

        {/* Progress bar */}
        {!showWelcome && phase === 'gathering' && activeTab === 'Conversations' && (
          <div className="progress-bar no-print">
            <div className="progress-fill" style={{ width: `${completeness}%` }} />
          </div>
        )}

        {/* Tab routing */}
        {activeTab === 'My documents'  && <div style={{ display:'flex', flex:1, overflow:'hidden', minHeight:0 }}><MyDocumentsTab switchToLibrary={() => setActiveTab('Legal library')} /></div>}
        {activeTab === 'Legal library' && <div style={{ display:'flex', flex:1, overflow:'hidden', minHeight:0 }}><LegalLibraryTab /></div>}

        {/* Conversations tab */}
        {activeTab === 'Conversations' && (
          <div className="chat-viewport">

            {/* Messages */}
            <div className="messages-area">
              <div className="messages-inner">
                {error && <div className="error-bar">⚠ {error}</div>}

                {/* Welcome screen */}
                {showWelcome && (
                  <div className="welcome-screen">
                    <h2 className="welcome-heading">How NyayaSakhi Can Help</h2>
                    <div className="feature-grid">
                      {[
                        { c: 'teal',   icon: '💬', title: 'Start with a conversation', desc: 'Describe your situation freely. I\'ll listen, ask the right questions, and guide you step by step through your legal options.', prompt: 'I need legal help with my situation' },
                        { c: 'yellow', icon: '📂', title: 'Get a full legal analysis', desc: 'After gathering key facts, I generate a complete legal analysis — predicted outcomes, timelines, and recommended next steps.', prompt: null },
                        { c: 'purple', icon: '⚖️', title: 'Explore the legal library', desc: 'Every answer is backed by Indian laws, IPC sections and court precedents — all viewable in the Sources panel next to your chat.', prompt: null },
                        { c: 'blue',   icon: '📋', title: 'View case documents', desc: 'Access AI-generated case summaries, evidence checklists, complaint templates, and court application formats.', prompt: null },
                      ].map((fc, i) => (
                        <div key={i} className={`feature-card ${fc.c}`} onClick={fc.prompt ? () => send(fc.prompt) : () => setActiveTab(i === 2 ? 'Legal library' : i === 3 ? 'My documents' : 'Conversations')}>
                          <div className="feature-card-icon">{fc.icon}</div>
                          <div className="feature-card-title">{fc.title}</div>
                          <div className="feature-card-desc">{fc.desc}</div>
                        </div>
                      ))}
                    </div>
                    <p className="quick-prompts-label">Common situations</p>
                    <div className="quick-prompts">
                      {[
                        'I am facing domestic violence at home',
                        'My husband is demanding dowry',
                        'I need help with divorce and custody',
                        'I want to file an FIR against harassment',
                        'I need maintenance from my husband',
                      ].map(p => (
                        <button key={p} className="quick-prompt-btn" onClick={() => send(p)}>{p}</button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Messages */}
                {!showWelcome && (
                  <div className="chat-messages">
                    {messages.map(msg => {
                      if (msg.role === 'user') return (
                        <div key={msg.id} className="msg-row user-row">
                          <div className="msg-body">
                            <div className="bubble user">{msg.content}</div>
                          </div>
                          <div className="msg-avatar user">U</div>
                        </div>
                      );

                      if (msg.isFinal && msg.finalResponse) return (
                        <div key={msg.id} className="msg-row bot-row">
                          <div className="msg-avatar bot"><img src="/bot-logo.jpeg" alt="Bot" /></div>
                          <div className="msg-body" style={{ maxWidth: '100%', flex: 1 }}>

                            {/* Inline citation cards (like PDF preview) */}
                            {msg.citations?.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                                {msg.citations.map((cit, ci) => (
                                  <div key={ci} className="citation-card" onClick={() => setSourcesOpen(true)}>
                                    <div className="citation-card-top">
                                      <div className="citation-card-icon">{cit.icon}</div>
                                      <div className="citation-card-meta">
                                        <div className="citation-card-title">{cit.title}</div>
                                        <div className="citation-card-sub">{cit.sub}</div>
                                      </div>
                                    </div>
                                    <div className="citation-card-body">
                                      <div className="citation-card-col"><strong>{cit.col1.label}</strong>{cit.col1.val}</div>
                                      <div className="citation-card-col"><strong>{cit.col2.label}</strong>{cit.col2.val}</div>
                                      <div className="citation-card-col"><strong>{cit.col3.label}</strong>{cit.col3.val}</div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Analysis card */}
                            <div className="analysis-card">
                              <div className="analysis-card-header">
                                <span style={{ fontSize: 15 }}>⚖️</span>
                                <span className="analysis-card-header-title">NyayaSakhi Legal Analysis</span>
                                <span className="analysis-badge">Complete</span>
                              </div>
                              {Object.entries(msg.finalResponse).map(([title, content]) => (
                                <div key={title} className="analysis-section">
                                  <span className={`analysis-section-pill ${PILL_CLS[title] || ''}`}>
                                    {SECTION_ICONS[title]} {title}
                                  </span>
                                  <div className="analysis-section-text" dangerouslySetInnerHTML={{ __html: md(content) }} />
                                </div>
                              ))}

                              {/* Action tags (LegalBot style) */}
                              {msg.actionTags?.length > 0 && (
                                <div className="action-tags-row">
                                  <span className="action-tags-label">Key findings:</span>
                                  {msg.actionTags.map((tag, i) => (
                                    <button key={i} className={`action-tag ${tag.cls}`} onClick={() => setSourcesOpen(true)}>
                                      {tag.icon} {tag.label} <span className="arrow">→</span>
                                    </button>
                                  ))}
                                  {accSections.length > 0 && (
                                    <button className="action-tag tag-blue" onClick={() => setSourcesOpen(true)}>
                                      📚 {accSections.reduce((a, s) => a + s.cards.length, 0)} legal sources <span className="arrow">→</span>
                                    </button>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );

                      return (
                        <div key={msg.id} className="msg-row bot-row">
                          <div className="msg-avatar bot"><img src="/bot-logo.jpeg" alt="Bot" /></div>
                          <div className="msg-body">
                            <div className="bubble bot" dangerouslySetInnerHTML={{ __html: md(msg.content) }} />
                          </div>
                        </div>
                      );
                    })}

                    {loading && (
                      <div className="msg-row bot-row no-print">
                        <div className="msg-avatar bot"><img src="/bot-logo.jpeg" alt="Bot" /></div>
                        <div className="msg-body">
                          <div className="typing-bubble"><span /><span /><span /></div>
                        </div>
                      </div>
                    )}

                    {exchangeCount > 0 && phase === 'gathering' && (
                      <div className="collected-wrap no-print">
                        <p className="collected-label">Collected so far:</p>
                        <div className="collected-pills">
                          {Object.entries(ATTR_LABELS).map(([k, label]) =>
                            resolvedAttrs[k]
                              ? <span key={k} className="collected-pill">✓ {label}</span>
                              : null
                          )}
                        </div>
                      </div>
                    )}
                    <div ref={chatEndRef} />
                  </div>
                )}
              </div>
            </div>

            {/* Sources panel — accordion style */}
            {sourcesOpen && accSections.length > 0 && (
              <aside className="sources-panel no-print">
                <div className="sources-hdr">
                  <div className="sources-hdr-left">
                    📚 Legal Sources
                    <span className="sources-count-badge">{accSections.reduce((a, s) => a + s.cards.length, 0)}</span>
                  </div>
                  <button className="sources-close" onClick={() => setSourcesOpen(false)}>✕</button>
                </div>
                <div className="sources-list" style={{ padding: 0 }}>
                  {accSections.map((sec, i) => <AccSection key={i} section={sec} />)}
                </div>
              </aside>
            )}
          </div>
        )}

        {/* Composer — only in Conversations */}
        {activeTab === 'Conversations' && (
          <div className="composer-wrap no-print">
            <div className="composer">
              <button className="composer-action-btn" title="Attach" onClick={() => alert('Upload coming soon')}>+</button>
              <button className="composer-action-btn" title="At-mention">@</button>
              <textarea
                ref={textareaRef}
                value={inputText}
                onChange={e => { setInputText(e.target.value); autoResize(); }}
                onKeyDown={handleKeyDown}
                placeholder="Ask NyayaSakhi anything…"
                disabled={loading}
                rows={1}
              />
              <button className="composer-action-btn" title="Voice">🎤</button>
              <button className="send-btn" onClick={() => send(inputText)} disabled={loading || !inputText.trim()}>➤</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
