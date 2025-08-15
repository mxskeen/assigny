import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatResponse {
  text: string;
  session_id: string;
}

const QUICK_ACTIONS = {
  patient: [
    "Check Dr. Ahuja's availability tomorrow",
    "I want to book an appointment with Dr. Ahuja tomorrow morning",
    "Show my appointments for today"
  ],
  doctor: [
    "How many appointments do I have today?",
    "How many appointments do I have tomorrow?",
    "List my appointments for today",
    "List my appointments for tomorrow",
    "Show patients with fever today",
    "Send today's summary to Slack"
  ]
};

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState<'patient' | 'doctor'>('patient');
  const [sessionId] = useState(() => crypto.randomUUID());

  const sendMessage = async (messageText?: string) => {
    const messageToSend = messageText || input;
    if (!messageToSend.trim() || loading) return;

    const userMessage: Message = { role: 'user', content: messageToSend };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch('http://localhost:8000/agent/chat', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageToSend,
          session_id: sessionId,
          user_type: role
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data: ChatResponse = await response.json();
      const assistantMessage: Message = { role: 'assistant', content: data.text };
      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.'
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage();
  };

  const handleQuickAction = (action: string) => {
    sendMessage(action);
  };

  const formatMessage = (content: string) => {
    return content.split('\n').map((line, index) => (
      <React.Fragment key={index}>
        {line}
        {index < content.split('\n').length - 1 && <br />}
      </React.Fragment>
    ));
  };

	return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto p-6">
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-800">
            Assigny - AI Appointment Assistant
          </h1>
        </header>

        <div className="mb-6 flex justify-center">
          <div className="flex bg-white rounded-lg p-1 shadow-sm border">
            <button
              onClick={() => setRole('patient')}
              className={`px-4 py-2 rounded-md transition-colors ${
                role === 'patient'
                  ? 'bg-blue-500 text-white'
                  : 'text-gray-600 hover:text-gray-800'
              }`}
            >
              Patient
            </button>
            <button
              onClick={() => setRole('doctor')}
              className={`px-4 py-2 rounded-md transition-colors ${
                role === 'doctor'
                  ? 'bg-blue-500 text-white'
                  : 'text-gray-600 hover:text-gray-800'
              }`}
            >
              Doctor
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <div className="bg-white rounded-xl shadow-lg border border-gray-200 h-[600px] flex flex-col overflow-hidden">              <div className="flex-1 p-6 overflow-y-auto bg-gradient-to-b from-gray-50 to-white">
                {messages.length === 0 && (
                  <div className="text-center text-gray-500 mt-12 mb-8">
                    <div className="w-16 h-16 mx-auto mb-4 bg-blue-100 rounded-full flex items-center justify-center">
                      <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                    </div>
                    <p className="text-lg font-medium mb-2">Welcome to Assigny!</p>
                    <p className="text-sm">I'm your AI appointment assistant. Ask me about appointments, schedules, or patient information.</p>
                  </div>
                )}
                
                <div className="space-y-4">
                  {messages.map((message, index) => (
                    <div
                      key={index}
                      className={`flex w-full ${message.role === 'user' ? 'justify-end' : 'justify-start'} message-fade-in`}
                      style={{ animationDelay: `${index * 0.1}s` }}
                    >
                      <div
                        className={`max-w-xs lg:max-w-lg px-4 py-3 rounded-3xl shadow-sm message-bubble ${
                          message.role === 'user'
                            ? 'bg-blue-500 text-white rounded-br-lg mr-4'
                            : 'bg-white text-gray-800 rounded-bl-lg border border-gray-200 ml-4'
                        }`}
                      >
                        <div className="whitespace-pre-wrap text-sm leading-relaxed">
                          {formatMessage(message.content)}
                        </div>
                        <div className={`text-xs mt-1 opacity-70 ${
                          message.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                        }`}>
                          {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                
                {loading && (
                  <div className="flex w-full justify-start mb-4 message-fade-in">
                    <div className="bg-white text-gray-800 px-4 py-3 rounded-3xl rounded-bl-lg border border-gray-200 shadow-sm ml-4">
                      <div className="flex items-center space-x-2">
                        <div className="typing-indicator">
                          <div className="typing-dot"></div>
                          <div className="typing-dot"></div>
                          <div className="typing-dot"></div>
                        </div>
                        <span className="text-sm text-gray-500">Assistant is typing...</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <form onSubmit={handleSubmit} className="p-4 border-t bg-white">
                <div className="flex gap-3 items-end">
                  <div className="flex-1 relative">
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder="Type your message..."
                      className="w-full px-4 py-3 pr-12 border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none text-sm"
                      disabled={loading}
                    />
                    <button
                      type="submit"
                      disabled={loading || !input.trim()}
                      className="absolute right-2 top-1/2 transform -translate-y-1/2 w-8 h-8 bg-blue-500 text-white rounded-full hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center transition-all duration-200 hover:scale-105"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                      </svg>
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>

          <div className="lg:col-span-1">
            <div className="bg-white rounded-xl shadow-lg border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-6 text-lg">
                {role === 'patient' ? '👤 Patient' : '👨‍⚕️ Doctor'} Dashboard
              </h3>
              
              <div className="space-y-3">
                {QUICK_ACTIONS[role].map((action, index) => (
                  <button
                    key={index}
                    onClick={() => handleQuickAction(action)}
                    disabled={loading}
                    className="w-full text-left px-4 py-3 text-sm bg-gradient-to-r from-gray-50 to-gray-100 hover:from-blue-50 hover:to-blue-100 hover:text-blue-700 rounded-xl transition-all duration-200 disabled:opacity-50 border border-gray-200 hover:border-blue-200 hover:shadow-sm"
                  >
                    {action}
                  </button>
                ))}
              </div>

              {role === 'doctor' && (
                <div className="mt-8 pt-6 border-t border-gray-200">
                  <h4 className="font-medium text-gray-700 mb-4 flex items-center">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 00-2-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                    </svg>
                    Session Stats
                  </h4>
                  <div className="space-y-3 text-sm">
                    <div className="bg-gray-50 p-3 rounded-lg">
                      <div className="text-gray-600">Session ID</div>
                      <div className="font-mono text-xs text-gray-800">{sessionId.slice(0, 8)}...</div>
                    </div>
                    <div className="bg-gray-50 p-3 rounded-lg">
                      <div className="text-gray-600">Role</div>
                      <div className="font-medium text-gray-800 capitalize">{role}</div>
                    </div>
                    <div className="bg-gray-50 p-3 rounded-lg">
                      <div className="text-gray-600">Messages</div>
                      <div className="font-medium text-gray-800">{messages.length}</div>
                    </div>
                  </div>
                </div>
              )}
				</div>
					</div>
				</div>
			</div>
		</div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
		<App />
  </React.StrictMode>
);