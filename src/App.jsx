import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

// ── Attribute display names ──────────────────────────────
const ATTR_LABELS = {
  relationship_type: 'Relationship',
  parties_involved: 'Parties',
  issue_types: 'Issue Type',
  timeline_duration: 'Timeline',
  living_situation: 'Living Situation',
  financial_dependency: 'Financial',
  children_involved: 'Children',
  prior_complaints: 'Prior Complaints',
  evidence_available: 'Evidence',
  relief_sought: 'Relief Sought',
};

// ── Analysis card icons ──────────────────────────────────
const ANALYSIS_ICONS = {
  'Victim Case Summary': { icon: '📋', cls: 'summary' },
  'Predicted Legal Outcomes': { icon: '⚖️', cls: 'outcomes' },
  'Expected Duration of the Case': { icon: '⏱️', cls: 'duration' },
  'Decision Recommendation': { icon: '✅', cls: 'recommendation' },
  'Reason for Recommendation': { icon: '💡', cls: 'reason' },
  'Recommended Next Actions': { icon: '📌', cls: 'actions' },
};

// ── Starter prompts ──────────────────────────────────────
const STARTER_PROMPTS = [
  { text: 'I am facing domestic violence at home', color: 'pink' },
  { text: 'My husband is demanding dowry', color: 'green' },
  { text: 'I need help with divorce and custody', color: 'yellow' },
];

function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^---$/gm, '<hr />')
    .replace(/^[\-\•]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br />');

  html = html.replace(/(<li>.*?<\/li>(?:\s*<br \/>)*)+/gs, (match) => {
    const cleaned = match.replace(/<br \/>/g, '');
    return `<ul>${cleaned}</ul>`;
  });

  return `<p>${html}</p>`;
}

// ── Main App Component ───────────────────────────────────
function App() {
  const [sessionId] = useState(() => `session-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`);
  const [showLanding, setShowLanding] = useState(true);
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [phase, setPhase] = useState('gathering');
  const [completeness, setCompleteness] = useState(0);
  const [resolvedAttrs, setResolvedAttrs] = useState({});
  const [exchangeCount, setExchangeCount] = useState(0);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const chatEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleTextareaInput = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }
  }, []);

  async function sendMessage(text) {
    if (!text.trim() || loading) return;

    const userMsg = { id: `user-${Date.now()}`, role: 'user', content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
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

      const botMsg = {
        id: `bot-${Date.now()}`,
        role: 'bot',
        content: data.response,
        isFinal: data.is_final,
        finalResponse: data.final_response,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (e) {
      setError(e.message || 'Something went wrong.');
      setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'bot', content: 'Issue processing message. Try again.' }]);
    } finally {
      setLoading(false);
    }
  }

  function handleSend() { sendMessage(inputText); }
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleNewChat() {
    setShowLanding(false);
    setMessages([]);
    setPhase('gathering');
    setCompleteness(0);
    setResolvedAttrs({});
    setExchangeCount(0);
    setError('');
    fetch(`${API_BASE}/chat/reset/${sessionId}`, { method: 'POST' }).catch(() => {});
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }

  if (showLanding) {
    return (
      <div className="landing-view">
        <nav className="landing-nav">
          <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
            <img src="/bot-logo.jpeg" alt="NyayaDepaaAI Logo" style={{width: '40px', height: '40px', borderRadius: '50%', objectFit: 'cover'}} />
            <h1 style={{margin: 0}}>NyayaDepaaAI</h1>
          </div>
          <button onClick={handleNewChat}>Start Consultation</button>
        </nav>
        
        <div className="bento-grid">
          <div className="bento-card hero-card">
            <h2>Empowering Women<br />Through AI Legal Counsel</h2>
            <p>A safe, highly confidential, and intelligent ethical legal advisor tailored for women navigating family law, domestic violence, and maintenance issues. Receive instant structural clarity on your legal standing.</p>
            <button className="hero-btn" onClick={handleNewChat}>Start AI Consultation Now</button>
          </div>

          <div className="bento-card text-card" style={{ backgroundColor: '#eff6ff', borderColor: '#bfdbfe' }}>
            <div className="card-icon">100%</div>
            <div>
              <h3>Private & Secure</h3>
              <p>Your conversations are strictly confidential. We maintain absolute privacy for sensitive family matters.</p>
            </div>
          </div>

          <div className="bento-card image-card">
            <img src="/img1.png" alt="Women receiving ethical AI help" />
          </div>

          <div className="bento-card image-card">
            <img src="/img2.png" alt="Digital scales of justice" />
          </div>

          <div className="bento-card text-card" style={{ backgroundColor: '#f1f5f9', borderColor: '#e2e8f0' }}>
            <div className="card-icon">✓</div>
            <div>
              <h3>Actionable Steps</h3>
              <p>Get structured summaries of your situation, possible legal recourses, and expected timelines instantly.</p>
            </div>
          </div>

          <div className="bento-card text-card" style={{ backgroundColor: '#ffffff', borderColor: '#e2e8f0', gridColumn: 'span 2' }}>
            <div>
              <h3>Supported Topics</h3>
              <p style={{ marginTop: '8px' }}>
                <span className="topic-pill dark" style={{marginRight: '8px', marginBottom: '8px', display: 'inline-block'}}>Domestic Violence</span>
                <span className="topic-pill dark" style={{marginRight: '8px', marginBottom: '8px', display: 'inline-block'}}>Divorce Laws</span>
                <span className="topic-pill dark" style={{marginRight: '8px', marginBottom: '8px', display: 'inline-block'}}>Child Custody</span>
                <span className="topic-pill dark" style={{marginRight: '8px', marginBottom: '8px', display: 'inline-block'}}>Maintenance Financials</span>
                <span className="topic-pill dark" style={{marginRight: '8px', marginBottom: '8px', display: 'inline-block'}}>Dowry Harassment</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const showWelcome = messages.length === 0;

  return (
    <main className="app-container grid-bg">
      
      {/* ── Desktop/Mobile Sidebar ────────────────────────────── */}
      <aside className={`app-sidebar ${isSidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-top">
          <div className="sidebar-logo">
            <h2>NyayaDepaaAI</h2>
          </div>
          <button className="new-chat-btn" onClick={handleNewChat}>
             New Consultation
          </button>
        </div>

        <div className="sidebar-nav">
          <p className="nav-label">Consultation history</p>
          <div className="nav-item active">
            <span className="nav-dot"></span>
            Current intake
          </div>
        </div>

        <div className="sidebar-bottom">
          <p>Confidential & Secure AI</p>
        </div>
      </aside>

      {/* Optional overlay for mobile sidebar */}
      {isSidebarOpen && <div className="sidebar-overlay" onClick={() => setIsSidebarOpen(false)}></div>}

      {/* ── Main Chat Area ────────────────────────────── */}
      <section className="app-main">
        
        {/* Top Header */}
        <header className="app-header header-no-print">
          <div className="header-icon-left">
            <button onClick={() => setIsSidebarOpen(prev => !prev)} className="icon-btn menu-btn">☰</button>
          </div>
          <div className="header-pill">
            NyayaDepaaAI {phase === 'gathering' ? 'Intake' : 'Analysis'}
          </div>
          <div className="header-icon-right">
            {!showWelcome && messages.length >= 2 && (
              <button className="icon-btn-highlight" onClick={() => window.print()}>Export PDF</button>
            )}
          </div>
        </header>

        {/* Progress Track (if actively gathering) */}
        {!showWelcome && phase === 'gathering' && (
          <div className="top-progress-bar header-no-print">
            <div className="top-progress-fill" style={{ width: `${completeness}%` }}></div>
          </div>
        )}

        <div className="messages-scroll-area printable-area">
          <div className="messages-content-wrapper">
            {error && <div className="error-banner header-no-print">⚠ {error}</div>}

            {/* Welcome Screen Area */}
            {showWelcome && (
              <div className="welcome-view header-no-print">
                <div className="welcome-header-area">
                  <div className="welcome-avatar-wrapper">
                    <div className="avatar main-avatar">
                      <img src="/bot-logo.jpeg" alt="NyayaDepaaAI Logo" />
                    </div>
                  </div>
                  <h1 className="welcome-title">Describe your situation</h1>
                </div>

                <div className="section-divider">
                  <h3>Chat focus</h3>
                  <span className="see-all">See All</span>
                </div>
                
                <div className="topic-pills">
                  <span className="topic-pill dark">Domestic Violence</span>
                  <span className="topic-pill dark">Divorce Laws</span>
                  <span className="topic-pill dark">Child Custody</span>
                  <span className="topic-pill dark">Maintenance Help</span>
                </div>

                <div className="section-divider">
                  <h3>Popular Prompts</h3>
                </div>

                <div className="prompt-cards-container">
                  {STARTER_PROMPTS.map((prompt, i) => (
                    <div key={i} className={`prompt-card bg-${prompt.color}`}>
                      <h4>{prompt.text}</h4>
                      <p>Guidance by NyayaDepaaAI</p>
                      <button onClick={() => sendMessage(prompt.text)}>Use this prompt</button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Messages Area */}
            {!showWelcome && (
              <div className="chat-messages-area">
                {messages.map((msg) => {
                  if (msg.role === 'user') {
                    return (
                      <div key={msg.id} className="chat-row user-row">
                        <div className="chat-bubble user-bubble">
                          <p>{msg.content}</p>
                        </div>
                        <div className="avatar tiny-avatar user">User</div>
                      </div>
                    );
                  }

                  if (msg.isFinal && msg.finalResponse) {
                    return (
                      <div key={msg.id} className="chat-row bot-row">
                        <div className="avatar tiny-avatar bot">
                          <img src="/bot-logo.jpeg" alt="NyayaDepaaAI Logo" />
                        </div>
                        <div className="analysis-board">
                          {Object.entries(msg.finalResponse).map(([title, content]) => (
                            <div key={title} className="analysis-item">
                              <span className="analysis-item-pill">{title}</span>
                              <div className="analysis-item-text">{content}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={msg.id} className="chat-row bot-row">
                      <div className="avatar tiny-avatar bot">
                        <img src="/bot-logo.jpeg" alt="NyayaDepaaAI Logo" />
                      </div>
                      <div 
                        className="chat-bubble bot-bubble"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                      />
                    </div>
                  );
                })}

                {loading && (
                  <div className="chat-row bot-row header-no-print">
                    <div className="avatar tiny-avatar bot">
                      <img src="/bot-logo.jpeg" alt="NyayaDepaaAI Logo" />
                    </div>
                    <div className="typing-dots-bubble">
                      <span /> <span /> <span />
                    </div>
                  </div>
                )}
                
                {/* Collected Attributes visually */}
                {exchangeCount > 0 && phase === 'gathering' && (
                  <div className="collected-data-wrapper header-no-print">
                    <p className="collected-title">Case Information Collected:</p>
                    <div className="collected-pills">
                      {Object.entries(ATTR_LABELS).map(([key, label]) => {
                        const resolved = resolvedAttrs[key];
                        if (!resolved) return null;
                        return <span key={key} className="collected-pill check">✓ {label}</span>;
                      })}
                    </div>
                  </div>
                )}

                <div ref={chatEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Bottom Composer */}
        <footer className="floating-composer header-no-print">
          <div className="composer-wrapper">
            <button className="attach-button" onClick={() => alert('File reading capability placeholder')}>
              Attach File
            </button>
            <textarea
              ref={textareaRef}
              value={inputText}
              onChange={(e) => {
                setInputText(e.target.value);
                handleTextareaInput();
              }}
              onKeyDown={handleKeyDown}
              placeholder="Type here..."
              disabled={loading}
              rows={1}
            />
            <button 
              className="send-button-primary" 
              onClick={handleSend}
              disabled={loading || !inputText.trim()}
            >
              ➤
            </button>

          </div>
        </footer>
      </section>
    </main>
  );
}

export default App;
