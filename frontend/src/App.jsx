import { useEffect, useState } from 'react'

const API_BASE = '/api'

/**
 * T02: basic chat layout connected to a test API endpoint.
 * The RAG answer flow (/chat) lands on Day 5 (T14); until then the
 * assistant echoes the question back so the wiring can be verified.
 */
export default function App() {
  const [backendStatus, setBackendStatus] = useState('Checking backend…')
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! Ask me anything about company documents.' },
  ])
  const [input, setInput] = useState('')

  // T02 completion check: React can send a request and display the response.
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((res) => res.json())
      .then((data) => setBackendStatus(`Backend OK — ${data.app} v${data.version}`))
      .catch(() => setBackendStatus('Backend unreachable — start FastAPI first (see README).'))
  }, [])

  function handleSend(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text) return
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: `(Placeholder answer) You asked: ${text}` },
    ])
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>AI Employee Knowledge Assistant</h1>
        <p className={`status ${backendStatus.startsWith('Backend OK') ? 'ok' : 'warn'}`}>
          {backendStatus}
        </p>
      </header>

      <section className="chat">
        <div className="messages">
          {messages.map((message, index) => (
            <div key={index} className={`message ${message.role}`}>
              {message.content}
            </div>
          ))}
        </div>

        <form className="composer" onSubmit={handleSend}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask a question about internal documents…"
            aria-label="Question"
          />
          <button type="submit" disabled={!input.trim()}>
            Send
          </button>
        </form>
      </section>
    </main>
  )
}
