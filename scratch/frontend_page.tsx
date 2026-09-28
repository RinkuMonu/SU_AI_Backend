"use client";
import { useState, useRef, useEffect } from "react";
import { Mic, Send, Globe, Layout, Palette, Phone, MapPin, Store, ChevronRight, Settings, CheckCircle2, RotateCcw, Clock, ArrowRight, Plus, Trash2 } from "lucide-react";
import { websiteBuilderService, ChatMessage } from "@/services/website-builder.service";

const CONVERSATION_STEPS = [
  "Understanding Business",
  "Collecting Requirements",
  "Business Information",
  "Brand Guidelines",
  "Template Selection",
];

const GENERATION_STEPS = [
  "Generating Website Content",
  "Building Pages",
  "Applying Responsive Design",
  "SEO Setup",
  "Final Quality Check"
];

export default function WebsiteBuilderPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [language, setLanguage] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [generatedSiteData, setGeneratedSiteData] = useState<any>(null);
  const [generationProgress, setGenerationProgress] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const savedSessionId = localStorage.getItem("website_builder_session_id");
    if (savedSessionId) {
      setSessionId(savedSessionId);
      loadSession(savedSessionId);
    }
  }, []);

  const loadSession = async (id: string) => {
    try {
      setLoading(true);
      const data = await websiteBuilderService.getSession(id);
      setMessages(data.messages || []);
      setLanguage(data.language || null);
      if (data.siteId) setSiteId(data.siteId);
      if (data.generatedSiteData) {
         setGeneratedSiteData(data.generatedSiteData);
         setGenerationProgress(GENERATION_STEPS);
      }
    } catch (e) {
      console.error("Failed to load session", e);
      localStorage.removeItem("website_builder_session_id");
      setSessionId(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const selectLanguage = async (lang: string) => {
    try {
      setLoading(true);
      setLanguage(lang);
      
      try {
        const data = await websiteBuilderService.startSession(lang);
        setSessionId(data.sessionId);
        localStorage.setItem("website_builder_session_id", data.sessionId);
        setMessages(data.messages || [
          { id: "init", role: "ai", content: `Great! We will continue in ${lang}. Let's build your website.` }
        ]);
      } catch (e: any) {
        const localSession = Date.now().toString();
        setSessionId(localSession);
        localStorage.setItem("website_builder_session_id", localSession);
        setMessages([
          { id: "init", role: "ai", content: `Great! We will continue in ${lang}. Let's start with your business name. What is it?` }
        ]);
      }
    } finally {
      setLoading(false);
    }
  };

  const startListening = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Your browser does not support voice input.");
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = language === "Hindi" || language === "Hinglish" ? "hi-IN" : "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => setIsListening(true);
    recognition.onresult = (event: any) => setInput(event.results[0][0].transcript);
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);
    recognition.start();
  };

  const handleSend = async (customMessage?: string, data?: any) => {
    const textToSend = customMessage || input;
    if (!textToSend.trim() && !data) return;

    const userMsg: ChatMessage = { id: Date.now().toString(), role: "user", content: textToSend, data };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    if (data?.action === 'generate') {
       setIsGenerating(true);
       setGenerationProgress(["Generating Website Content"]);
    }

    try {
      if (sessionId) {
        if (siteId && data?.action === 'revise') {
           const res = await websiteBuilderService.reviseSite(siteId, textToSend);
           setGeneratedSiteData(res.generatedSiteData);
           setMessages(prev => [...prev, { id: Date.now().toString(), role: "ai", content: "I have updated the website based on your feedback." }]);
        } else {
           const res = await websiteBuilderService.sendMessage(sessionId, textToSend, data);
           if (res.messages) {
              setMessages(res.messages);
           } else {
              setMessages(prev => [...prev, { id: Date.now().toString(), role: "ai", content: res.message || "Done.", type: res.type, data: res.data }]);
           }
           if (res.siteId) setSiteId(res.siteId);
           if (res.generatedSiteData) {
              setGeneratedSiteData(res.generatedSiteData);
              setIsGenerating(false);
              setGenerationProgress(GENERATION_STEPS);
           }
        }
      } else {
        simulateBackendResponse(textToSend, data);
      }
    } catch (e: any) {
      const errMsg = e?.response?.data?.message || "Something went wrong. Please try again.";
      setMessages(prev => [...prev, { id: Date.now().toString(), role: "ai", content: errMsg }]);
      setIsGenerating(false);
    } finally {
      setLoading(false);
    }
  };

  const simulateBackendResponse = (text: string, data?: any) => {
     setTimeout(() => {
        if (text.toLowerCase().includes("recommend")) {
           setMessages(prev => [...prev, {
              id: Date.now().toString(), role: "ai", content: "Here are some recommendations:", type: "recommendation",
              options: [
                 { id: "rec1", name: "Modern Tech", description: "Sleek and clean", palette: "Dark", style: "Minimal" },
                 { id: "rec2", name: "Vibrant E-commerce", description: "Colorful and bright", palette: "Colorful", style: "Vibrant" },
                 { id: "rec3", name: "Elegant Corporate", description: "Professional and trustworthy", palette: "Blue", style: "Corporate" }
              ]
           }]);
        } else if (data?.action === 'select_template') {
           setMessages(prev => [...prev, {
              id: Date.now().toString(), role: "ai", content: `You selected ${data.templateName}. Here is the final summary:`, type: "summary",
              data: { business: "My Business", theme: data.templateName, language: language }
           }]);
        } else if (data?.action === 'generate') {
           
           // Mocking step-by-step generation progress
           let step = 0;
           const interval = setInterval(() => {
              step++;
              if (step < GENERATION_STEPS.length) {
                 setGenerationProgress(GENERATION_STEPS.slice(0, step + 1));
              } else {
                 clearInterval(interval);
                 setIsGenerating(false);
                 setGeneratedSiteData({
                    home: { hero: "Welcome", features: [] },
                    about: { content: "About us" }
                 });
                 setSiteId("fake_site_id");
                 setMessages(prev => [...prev, {
                    id: Date.now().toString(), role: "ai", content: "Website generated successfully! You can now preview it and ask for revisions."
                 }]);
              }
           }, 1200);

        } else if (messages.length === 1) {
           setMessages(prev => [...prev, {
              id: Date.now().toString(), role: "ai", content: `I already have your business name as 'Royal Threads'. Should I use it?`, type: "confirmation",
              options: [{ label: "Yes", action: "yes" }, { label: "Change", action: "change" }, { label: "Skip", action: "skip" }]
           }]);
        } else {
           setMessages(prev => [...prev, {
              id: Date.now().toString(), role: "ai", content: "I understand. Let me check the templates for you.", type: "template_selection",
              options: [
                 { id: "tpl1", name: "Premium", style: "Luxury", palette: "Gold/Black", bestFor: "Jewelry" },
                 { id: "tpl2", name: "Modern", style: "Clean", palette: "White/Blue", bestFor: "Tech" },
                 { id: "tpl3", name: "Elegant", style: "Soft", palette: "Pastel", bestFor: "Fashion" }
              ]
           }]);
        }
     }, 1000);
  };

  const renderMessageContent = (msg: ChatMessage) => {
    if (msg.type === "confirmation" && msg.options) {
       return (
          <div className="space-y-4">
             <p>{msg.content}</p>
             <div className="flex flex-wrap gap-2">
                {msg.options.map((opt: any, i: number) => (
                   <button key={i} onClick={() => handleSend(opt.label)} className="px-4 py-2 bg-surface-elevated hover:bg-brand-purple/20 border border-border rounded-lg text-sm font-medium transition-colors">
                      {opt.label}
                   </button>
                ))}
             </div>
          </div>
       )
    }

    if (msg.type === "recommendation" || msg.type === "template_selection") {
       return (
          <div className="space-y-4">
             <p>{msg.content}</p>
             <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {msg.options?.map((opt: any, i: number) => (
                   <div key={i} className="p-4 bg-surface-elevated border border-border rounded-xl space-y-2 hover:border-brand-purple/50 transition-colors cursor-pointer" onClick={() => handleSend(`Selected ${opt.name}`, { action: "select_template", templateId: opt.id, templateName: opt.name })}>
                      <div className="h-24 bg-surface rounded-lg mb-3 flex items-center justify-center text-xs text-text-muted">Preview</div>
                      <h4 className="font-semibold text-white">{opt.name}</h4>
                      <p className="text-xs text-text-muted">{opt.description || opt.style}</p>
                      <div className="flex gap-2">
                         <span className="text-[10px] px-2 py-1 bg-background rounded-md text-text-muted">{opt.palette}</span>
                         {opt.bestFor && <span className="text-[10px] px-2 py-1 bg-background rounded-md text-text-muted">{opt.bestFor}</span>}
                      </div>
                      <button className="w-full mt-2 py-1.5 bg-brand-purple/20 text-brand-purple rounded-md text-xs font-semibold hover:bg-brand-purple hover:text-white transition-colors">Select</button>
                   </div>
                ))}
             </div>
          </div>
       )
    }

    if (msg.type === "summary") {
       return (
          <div className="space-y-4">
             <p>{msg.content}</p>
             <div className="p-4 bg-surface-elevated border border-border rounded-xl space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-text-muted">Business</span><span className="font-medium">{msg.data?.business}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Language</span><span className="font-medium">{msg.data?.language}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Theme</span><span className="font-medium">{msg.data?.theme}</span></div>
             </div>
             <div className="flex flex-col gap-2">
                <button onClick={() => handleSend("Build My Website", { action: "generate" })} className="w-full py-2 bg-gradient-to-r from-brand-purple to-brand-pink text-white rounded-lg font-semibold hover:opacity-90 transition-opacity">
                   Build My Website
                </button>
                <button onClick={() => handleSend("Edit Information")} className="w-full py-2 bg-surface hover:bg-surface-elevated text-white rounded-lg font-medium transition-colors text-sm border border-border">
                   Edit Information
                </button>
             </div>
          </div>
       )
    }

    if (msg.type === "generation_status") {
       // Generation status now handled in the right panel UI synchronously with isGenerating
       return null;
    }

    return <p className="whitespace-pre-wrap">{msg.content}</p>;
  };

  const getActiveConversationStep = () => {
     if (isGenerating || generatedSiteData) return CONVERSATION_STEPS.length;
     const userMsgCount = messages.filter(m => m.role === 'user').length;
     return Math.min(Math.floor(userMsgCount / 2), CONVERSATION_STEPS.length - 1);
  };

  const handleNewChat = () => {
    localStorage.removeItem("website_builder_session_id");
    setSessionId(null);
    setSiteId(null);
    setLanguage(null);
    setMessages([]);
    setGeneratedSiteData(null);
    setGenerationProgress([]);
    setIsGenerating(false);
  };

  const handleClearChat = async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const res = await websiteBuilderService.clearSession(sessionId);
      if (res.messages) {
         setMessages(res.messages);
      }
      setGeneratedSiteData(null);
      setGenerationProgress([]);
      setIsGenerating(false);
    } catch(e) {
      console.error("Failed to clear chat", e);
    } finally {
      setLoading(false);
    }
  };

  const activeConvStepIdx = getActiveConversationStep();

  return (
    <div className="flex flex-col lg:flex-row h-[calc(100vh-100px)] gap-4 -mt-2">
      
      {/* ── LEFT: Chatbot (75-80%) ── */}
      <div className="w-full lg:w-[75%] xl:w-[80%] flex flex-col bg-surface border border-border rounded-2xl overflow-hidden shadow-2xl relative">
        
        {/* Header */}
        <div className="px-5 py-4 border-b border-border bg-surface-elevated flex items-center justify-between shrink-0">
           <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-gradient-to-br from-brand-purple to-brand-pink flex items-center justify-center shadow-lg">
                 <Globe className="text-white" size={18} />
              </div>
              <div>
                 <h2 className="font-bold text-base leading-tight text-white">AI Website Builder</h2>
                 <p className="text-xs text-text-muted">SevenUnique AI Assistant</p>
              </div>
           </div>

           <div className="flex gap-2">
              <button 
                 onClick={handleClearChat}
                 disabled={!sessionId || loading}
                 className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-elevated border border-border rounded-lg text-xs font-medium text-text-muted hover:text-red-400 transition-colors disabled:opacity-50"
              >
                 <Trash2 size={14} />
                 Clear
              </button>
              <button 
                 onClick={handleNewChat}
                 className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-elevated border border-border rounded-lg text-xs font-medium text-text-muted hover:text-white transition-colors"
              >
                 <Plus size={14} />
                 New Chat
              </button>
           </div>
        </div>

        {!language ? (
           <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-6 overflow-y-auto">
              <div className="w-20 h-20 bg-brand-purple/10 rounded-full flex items-center justify-center mb-2">
                 <Globe className="text-brand-purple" size={40} />
              </div>
              <div>
                 <h3 className="text-2xl font-bold text-white mb-2">Choose your language</h3>
                 <p className="text-text-muted text-sm max-w-sm">To start building your website, please select the language you are most comfortable with.</p>
              </div>
              <div className="flex flex-col w-full max-w-xs gap-3 mt-4">
                 <button onClick={() => selectLanguage("English")} className="p-3 bg-surface-elevated hover:bg-brand-purple/20 border border-border rounded-xl font-medium transition-all hover:scale-[1.02]">English</button>
                 <button onClick={() => selectLanguage("Hindi")} className="p-3 bg-surface-elevated hover:bg-brand-purple/20 border border-border rounded-xl font-medium transition-all hover:scale-[1.02]">हिन्दी (Hindi)</button>
                 <button onClick={() => selectLanguage("Hinglish")} className="p-3 bg-surface-elevated hover:bg-brand-purple/20 border border-border rounded-xl font-medium transition-all hover:scale-[1.02]">Hinglish</button>
              </div>
           </div>
        ) : (
           <>
              {/* Messages Area - Independently Scrollable */}
              <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-5 custom-scrollbar">
                 {messages.map((msg, i) => (
                    msg.type !== 'generation_status' && (
                    <div key={msg.id || i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                       <div className={`max-w-[85%] md:max-w-[75%] rounded-2xl p-4 ${msg.role === 'user' ? 'bg-gradient-to-r from-brand-purple to-brand-pink text-white rounded-br-sm' : 'bg-surface-elevated border border-border text-gray-200 rounded-bl-sm shadow-sm'}`}>
                          {renderMessageContent(msg)}
                       </div>
                    </div>
                    )
                 ))}
                 {loading && !isGenerating && (
                    <div className="flex justify-start">
                       <div className="max-w-[75%] rounded-2xl p-4 bg-surface-elevated border border-border text-gray-400 rounded-bl-sm flex gap-2 items-center shadow-sm">
                          <span className="w-2 h-2 rounded-full bg-brand-purple animate-bounce" style={{ animationDelay: '0ms' }} />
                          <span className="w-2 h-2 rounded-full bg-brand-pink animate-bounce" style={{ animationDelay: '150ms' }} />
                          <span className="w-2 h-2 rounded-full bg-brand-coral animate-bounce" style={{ animationDelay: '300ms' }} />
                       </div>
                    </div>
                 )}
                 <div ref={endRef} />
              </div>

              {/* Input Area - Fixed at Bottom */}
              <div className="p-4 bg-surface border-t border-border shrink-0">
                 <div className="flex items-center gap-2 bg-background border border-border rounded-full p-1.5 pl-4 focus-within:border-brand-purple/50 transition-colors">
                    <input
                       type="text"
                       value={input}
                       onChange={e => setInput(e.target.value)}
                       onKeyDown={e => e.key === 'Enter' && handleSend()}
                       placeholder={generatedSiteData ? "Ask for revisions (e.g. Change color to blue)" : "Type your message..."}
                       className="flex-1 bg-transparent border-none outline-none text-sm text-white placeholder-text-muted"
                       disabled={loading || isGenerating}
                    />
                    <button
                       onClick={startListening}
                       className={`p-2 rounded-full transition-colors ${isListening ? 'bg-red-500/20 text-red-500' : 'text-text-muted hover:bg-surface-elevated'}`}
                       disabled={loading || isGenerating}
                    >
                       <Mic size={18} />
                    </button>
                    <button
                       onClick={() => handleSend(undefined, generatedSiteData ? { action: 'revise' } : undefined)}
                       disabled={!input.trim() || loading || isGenerating}
                       className="p-2.5 bg-gradient-to-r from-brand-purple to-brand-pink text-white rounded-full disabled:opacity-50 transition-opacity"
                    >
                       <Send size={16} className="ml-0.5" />
                    </button>
                 </div>
              </div>
           </>
        )}
      </div>

      {/* ── RIGHT: Progress / Preview (20-25%) ── */}
      <div className="w-full lg:w-[25%] xl:w-[20%] flex flex-col gap-4 mt-4 lg:mt-0 h-full shrink-0">
         
         {!generatedSiteData && !isGenerating ? (
           /* ── PRE-GENERATION: Detailed Conversation Progress ── */
           <div className="bg-surface border border-border rounded-2xl overflow-hidden shadow-xl flex flex-col h-full max-h-[100%]">
              <div className="p-4 border-b border-border bg-surface-elevated shrink-0">
                 <h3 className="font-semibold text-white flex items-center gap-2 text-sm">
                    <Layout size={16} className="text-brand-pink" />
                    Build Progress
                 </h3>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-1 custom-scrollbar">
                  {CONVERSATION_STEPS.map((step, idx) => {
                     const isDone = idx < activeConvStepIdx;
                     const isCurrent = idx === activeConvStepIdx && language;
                     
                     return (
                        <div key={idx} className={`p-2.5 rounded-lg flex items-center gap-3 transition-all ${isDone ? 'bg-surface/50' : isCurrent ? 'bg-brand-purple/10 border border-brand-purple/30' : 'opacity-50'}`}>
                           <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${isDone ? 'bg-green-500/20 text-green-400' : isCurrent ? 'bg-brand-purple text-white animate-pulse' : 'bg-surface-elevated text-text-muted'}`}>
                                 {isDone ? <CheckCircle2 size={12} /> : isCurrent ? <RotateCcw size={10} className="animate-spin" /> : <div className="w-1.5 h-1.5 rounded-full bg-text-muted" />}
                           </div>
                           <span className={`text-[11px] font-medium leading-tight ${isDone || isCurrent ? 'text-white' : 'text-text-muted'}`}>{step}</span>
                        </div>
                     );
                  })}
                  <div className="pt-2 mt-2 border-t border-border/50 opacity-40">
                     <div className="p-2.5 flex items-center gap-3">
                        <div className="w-5 h-5 rounded-full bg-surface-elevated flex items-center justify-center shrink-0">
                           <div className="w-1.5 h-1.5 rounded-full bg-text-muted" />
                        </div>
                        <span className="text-[11px] font-medium text-text-muted">Website Generation</span>
                     </div>
                  </div>
              </div>
           </div>
         ) : isGenerating ? (
           /* ── DURING GENERATION: Detailed Generation Progress ── */
           <div className="bg-surface border border-border rounded-2xl overflow-hidden shadow-xl flex flex-col h-full">
              <div className="p-4 border-b border-border bg-surface-elevated shrink-0">
                 <h3 className="font-semibold text-white flex items-center gap-2 text-sm">
                    <Settings size={16} className="text-brand-purple animate-spin" />
                    Building Website
                 </h3>
                 <div className="mt-3 bg-background rounded-full h-1.5 overflow-hidden flex items-center">
                     <div className="bg-gradient-to-r from-brand-purple to-brand-pink h-full transition-all duration-500" style={{ width: `${(generationProgress.length / GENERATION_STEPS.length) * 100}%` }}></div>
                 </div>
                 <p className="text-[10px] text-brand-pink mt-2 flex items-center gap-1.5 font-medium">
                    <Clock size={10} /> Estimated time remaining: ~2 min
                 </p>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-1 custom-scrollbar">
                 {GENERATION_STEPS.map((step, idx) => {
                     const isDone = idx < generationProgress.length - 1;
                     const isCurrent = idx === generationProgress.length - 1;
                     const isPending = idx > generationProgress.length - 1;
                     return (
                        <div key={idx} className={`p-2.5 rounded-lg flex items-center gap-3 transition-all ${isDone ? 'bg-surface/50' : isCurrent ? 'bg-brand-purple/10 border border-brand-purple/30' : 'opacity-40'}`}>
                           <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${isDone ? 'bg-green-500/20 text-green-400' : isCurrent ? 'bg-brand-purple text-white animate-pulse' : 'bg-surface-elevated text-text-muted'}`}>
                                 {isDone ? <CheckCircle2 size={12} /> : isCurrent ? <RotateCcw size={10} className="animate-spin" /> : <div className="w-1.5 h-1.5 rounded-full bg-text-muted" />}
                           </div>
                           <span className={`text-[11px] font-medium leading-tight ${isDone || isCurrent ? 'text-white' : 'text-text-muted'}`}>{step}</span>
                        </div>
                     )
                 })}
              </div>
           </div>
         ) : (
           /* ── SUCCESS STATE: Completed & Preview ── */
           <div className="bg-surface border border-border rounded-2xl overflow-hidden shadow-xl p-4 flex flex-col h-full lg:h-auto">
              <div className="flex items-center gap-2 mb-4">
                 <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center">
                    <CheckCircle2 size={14} className="text-green-500" />
                 </div>
                 <h3 className="font-bold text-white text-sm">Website Ready</h3>
              </div>
              
              <p className="text-[11px] text-text-muted mb-4 flex items-center gap-1.5">
                 <Clock size={12} /> Generation Completed
              </p>

              {/* Compact Website Preview Frame */}
              <div className="w-full h-40 bg-white rounded-lg shadow-inner overflow-hidden flex flex-col relative text-black font-sans mb-4 border border-border/50">
                 <div className="bg-gray-100 p-2 flex justify-between items-center border-b">
                    <div className="font-bold text-[9px] tracking-tight text-gray-800">YourBrand</div>
                    <div className="flex gap-1.5 text-[7px] font-medium text-gray-600">
                       <span>Home</span>
                       <span>About</span>
                    </div>
                 </div>
                 <div className="flex-1 bg-gray-900 text-white p-3 text-center flex flex-col items-center justify-center">
                    <h1 className="text-xs font-extrabold mb-1">Welcome</h1>
                    <p className="text-[8px] text-gray-300 max-w-[120px] mx-auto mb-2 leading-tight">AI generated site preview.</p>
                    <button className="bg-white text-black px-2 py-0.5 rounded-full font-bold text-[7px]">Shop</button>
                 </div>
              </div>

              <div className="mt-auto space-y-2">
                 <button 
                    onClick={() => window.open(`/preview/${siteId || 'demo'}`, '_blank')}
                    className="w-full py-2 bg-brand-purple text-white rounded-lg text-xs font-medium hover:bg-brand-purple/90 transition-colors flex items-center justify-center gap-2 shadow-lg shadow-brand-purple/20">
                    <Globe size={14} /> Preview Website
                 </button>
                 <button 
                    onClick={() => {
                       const inputEl = document.querySelector('input[type="text"]') as HTMLInputElement;
                       if (inputEl) inputEl.focus();
                    }}
                    className="w-full py-2 bg-surface-elevated text-white rounded-lg text-xs font-medium hover:bg-surface-elevated/80 transition-colors border border-border flex items-center justify-center gap-2">
                    Continue Editing <ArrowRight size={14} />
                 </button>
              </div>
           </div>
         )}
      </div>

    </div>
  );
}
