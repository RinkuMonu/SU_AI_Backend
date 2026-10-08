"use client";
import { useState, useRef, useEffect } from "react";
import { Mic, Send, Globe, Layout, Palette, Phone, MapPin, Store, ChevronRight, Settings, CheckCircle2, RotateCcw, Clock, ArrowRight, Plus, Trash2, Maximize2, Minimize2, Download } from "lucide-react";
import { websiteBuilderService, ChatMessage } from "@/services/website-builder.service";

const generateHtmlFromJSON = (rawData: any) => {
  if (!rawData) return "";
  
  let data = rawData;
  if (typeof rawData === 'string') {
    try {
      data = JSON.parse(rawData);
    } catch (e) {
      // If it's just an HTML string or plain text, return as is
      return rawData;
    }
  }

  if (data.html) return data.html;

  let pages = Array.isArray(data) ? data : data.pages ? data.pages : [data];
  if (!pages || pages.length === 0) return "<h1>No data available</h1>";


    const logoUrl = data.logo?.url || data.logo || null;
    const bName = data.business_name || 'MyBusiness';
    const primaryColor = data.theme?.primary || "#4f46e5";
    const secondaryColor = data.theme?.secondary || "#4338ca";
      let bodyHtml = "";
  
  pages.forEach((page: any) => {
    if (page.sections) {
      page.sections.forEach((section: any) => {
        const sectionId = section.title ? `section-${section.title.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase()}` : `section-${Math.random().toString(36).substring(7)}`;
        if (section.type === "hero") {
          bodyHtml += `
            <section id="${sectionId}" class="relative bg-white overflow-hidden border-b border-gray-100">
              <div class="max-w-7xl mx-auto">
                <div class="relative z-10 pb-8 bg-white sm:pb-16 md:pb-20 lg:max-w-2xl lg:w-full lg:pb-28 xl:pb-32 pt-20 px-4 sm:px-6 lg:px-8">
                  <main class="mt-10 mx-auto max-w-7xl px-4 sm:mt-12 sm:px-6 md:mt-16 lg:mt-20 lg:px-8 xl:mt-28">
                    <div class="sm:text-center lg:text-left">
                      <h1 class="text-4xl tracking-tight font-extrabold text-gray-900 sm:text-5xl md:text-6xl">
                        <span class="block xl:inline text-primary">${section.title || ''}</span>
                      </h1>
                      <p class="mt-3 text-base text-gray-500 sm:mt-5 sm:text-lg sm:max-w-xl sm:mx-auto md:mt-5 md:text-xl lg:mx-0">
                        ${section.subtitle || section.description || ''}
                      </p>
                      <div class="mt-5 sm:mt-8 sm:flex sm:justify-center lg:justify-start">
                        ${section.cta ? `
                        <div class="rounded-md shadow">
                          <a href="javascript:void(0)" class="w-full flex items-center justify-center px-8 py-3 border border-transparent text-base font-medium rounded-md text-white bg-primary hover:bg-secondary md:py-4 md:text-lg md:px-10">
                            ${section.cta}
                          </a>
                        </div>` : ''}
                      </div>
                    </div>
                  </main>
                </div>
              </div>
              <div class="lg:absolute lg:inset-y-0 lg:right-0 lg:w-1/2">
                <img class="h-56 w-full object-cover sm:h-72 md:h-96 lg:w-full lg:h-full shadow-2xl" src="${section.image_url || 'https://images.unsplash.com/photo-1551434678-e076c223a692?ixlib=rb-1.2.1&ixid=eyJhcHBfaWQiOjEyMDd9&auto=format&fit=crop&w=2850&q=80'}" alt="">
              </div>
            </section>
          `;
        } else if (section.type === "features" || section.type === "services" || section.items) {
          bodyHtml += `
            <section id="${sectionId}" class="py-16 bg-gray-50 border-b border-gray-100">
              <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="text-center">
                  <h2 class="text-3xl font-extrabold text-gray-900 sm:text-4xl">${section.title || section.type || ''}</h2>
                  ${section.subtitle ? `<p class="mt-4 text-lg text-gray-500">${section.subtitle}</p>` : ''}
                </div>
                <div class="mt-12">
                  <div class="grid grid-cols-1 gap-10 sm:grid-cols-2 lg:grid-cols-3">
                    ${(section.items || []).map((item: any) => `
                      <div class="bg-white rounded-xl shadow-lg overflow-hidden transition hover:-translate-y-1 hover:shadow-xl duration-300">
                        ${item.image_url ? `<img class="w-full h-48 object-cover" src="${item.image_url}" alt="${item.title || ''}">` : ''}
                        <div class="p-6">
                          <h3 class="text-xl font-bold text-gray-900">${item.title || ''}</h3>
                          <p class="mt-2 text-sm text-gray-600">${item.description || ''}</p>
                          ${item.price ? `<p class="mt-4 text-lg font-bold text-primary">${item.price}</p>` : ''}
                        </div>
                      </div>
                    `).join('')}
                  </div>
                </div>
              </div>
            </section>
          `;
        } else {
           bodyHtml += `
             <section id="${sectionId}" class="py-16 bg-white overflow-hidden border-b border-gray-100">
                <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                  <div class="lg:grid lg:grid-cols-2 lg:gap-12 lg:items-center">
                    <div>
                      <h2 class="text-3xl font-extrabold text-gray-900 sm:text-4xl">${section.title || section.type || ''}</h2>
                      <p class="mt-4 text-lg text-gray-500">${section.description || section.content || ''}</p>
                    </div>
                    ${section.image_url ? `
                    <div class="mt-10 lg:mt-0">
                      <img class="rounded-xl shadow-2xl" src="${section.image_url}" alt="">
                    </div>
                    ` : ''}
                  </div>
                </div>
             </section>
           `;
        }
      });
    }
  });

  return `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Generated Website</title>
      <script src="https://cdn.tailwindcss.com"></script>
      <script>
        tailwind.config = {
          theme: {
            extend: {
              colors: {
                primary: '${primaryColor}',
                secondary: '${secondaryColor}'
              }
            }
          }
        }
      </script>
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
        html { scroll-behavior: smooth; }
        body { font-family: 'Outfit', sans-serif; }
      </style>
    </head>
    <body class="bg-gray-50 text-gray-900 antialiased">
      <nav class="bg-white/90 backdrop-blur-md shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div class="flex justify-between h-20 items-center">
            <div class="flex-shrink-0 flex items-center">
              ${logoUrl ? `<img src="${logoUrl}" alt="${bName}" class="h-10 w-auto" />` : `<span class="text-2xl font-black text-primary tracking-tight">${bName}</span>`}
            </div>
            <div class="hidden md:flex items-center space-x-8">
              ${pages[0]?.sections ? pages[0].sections.filter((s:any)=>s.title && s.type !== 'hero').map((s:any) => `<a href="javascript:void(0)" onclick="document.getElementById('section-${s.title.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase()}').scrollIntoView({behavior: 'smooth'})" class="text-gray-600 hover:text-primary text-sm font-semibold transition">${s.title}</a>`).join('') : ''}
              <button class="bg-primary text-white px-6 py-2.5 rounded-full font-bold hover:bg-secondary transition shadow-lg">Order Now</button>
            </div>
          </div>
        </div>
      </nav>
      
      ${bodyHtml}
      
      <footer class="bg-gray-900 text-white border-t border-gray-800">
        <div class="max-w-7xl mx-auto py-16 px-4 sm:px-6 lg:px-8">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-12 text-center md:text-left">
            <div>
               <h3 class="text-2xl font-black mb-4">${logoUrl ? `<img src="${logoUrl}" alt="${bName}" class="h-10 w-auto mb-2" />` : bName}</h3>
               <p class="text-gray-400 text-sm leading-relaxed">Delivering happiness to your doorstep in 30 minutes or less. Fresh, fast, and always delicious.</p>
            </div>
            <div>
               <h3 class="text-lg font-bold mb-4 text-white">Quick Links</h3>
               <ul class="space-y-3 text-sm text-gray-400">
                  <li><a href="javascript:void(0)" class="hover:text-indigo-400 transition">About Us</a></li>
                  <li><a href="javascript:void(0)" class="hover:text-indigo-400 transition">Careers</a></li>
                  <li><a href="javascript:void(0)" class="hover:text-indigo-400 transition">Contact</a></li>
               </ul>
            </div>
            <div>
               <h3 class="text-lg font-bold mb-4 text-white">Contact Us</h3>
               <p class="text-gray-400 text-sm leading-relaxed">support@${bName.toLowerCase().replace(/\s+/g, "")}.com<br/>+1 (555) 123-4567</p>
            </div>
          </div>
          <div class="border-t border-gray-800 mt-12 pt-8 text-center">
            <p class="text-sm text-gray-500">
              &copy; 2026 ${bName}, Inc. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </body>
    </html>
  `;
}

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
  const [isFullscreen, setIsFullscreen] = useState(false);
  
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const initSession = async () => {
      const savedSessionId = localStorage.getItem("website_builder_session_id");
      if (savedSessionId) {
        setSessionId(savedSessionId);
        loadSession(savedSessionId);
      } else {
        try {
          const data = await websiteBuilderService.startSession("English");
          setSessionId(data.sessionId);
          localStorage.setItem("website_builder_session_id", data.sessionId);
          if (data.messages) setMessages(data.messages);
        } catch (e) {
          console.error("Failed to start session", e);
        }
      }
    };
    initSession();
  }, []);

  const handleDownloadZip = async () => {
    if (!generatedSiteData) return;
    try {
      const htmlContent = generateHtmlFromJSON(generatedSiteData);
      const JSZip = (await import('jszip')).default;
      const zip = new JSZip();
      zip.file("index.html", htmlContent);
      const content = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(content);
      const a = document.createElement("a");
      a.href = url;
      a.download = "website.zip";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Error creating zip", e);
    }
  };

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
        setMessages(prev => [...prev, {
           id: Date.now().toString(), role: "ai", content: "Error: The AI Backend is currently unreachable or your session failed to initialize. Please check your connection or refresh the page."
        }]);
     }, 1000);
  };



       
  
  const handleOptionSelect = (option: any, msgType?: string) => {
    if (option.action === "upload_logo") {
      fileInputRef.current?.click();
      return;
    }
    if (msgType === "template_selection") {
      handleSend(`I select the ${option.name} template.`, { action: "select_template", templateId: option.id, templateName: option.name });
    } else if (msgType === "recommendation") {
      handleSend(`Recommend template: ${option.name}`, { action: "recommend", templateId: option.id });
    } else {
      handleSend(option.label, { action: option.action });
    }
  };

  // Phase 3: Two-Pane Layout Architecture

  return (
    <div className="flex h-[calc(100vh-64px)] w-full bg-[#0B0F19] overflow-hidden text-gray-200">
      
      {/* LEFT PANE: AI EDITOR CHAT */}
      <div className="w-[400px] min-w-[400px] flex flex-col border-r border-white/10 bg-[#111827] z-10 relative shadow-xl">
        <div className="p-4 border-b border-white/10 bg-gradient-to-r from-purple-900/40 to-pink-900/40 flex justify-between items-center">
          <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Globe className="w-5 h-5 text-purple-400" />
            AI Website Editor
          </h2>
          <p className="text-xs text-gray-400 mt-1">Chat to build & modify your site</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setMessages([])} className="text-xs px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-gray-200">Clear</button>
            <button onClick={() => { setMessages([]); setGeneratedSiteData(null); setSiteId(null); setSessionId(null); localStorage.removeItem("website_builder_session_id"); }} className="text-xs px-2 py-1 bg-purple-600 hover:bg-purple-700 rounded text-white">New Chat</button>
          </div>
        </div>
        
        {/* Chat History Area */}
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
          <div className="bg-white/5 p-3 rounded-lg border border-white/10 text-sm">
            <p className="text-gray-300">👋 Welcome! Tell me what kind of website you want to build, or ask me to edit an existing section.</p>
          </div>
          {messages.map((msg, i) => (
             <div key={i} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'} mb-4`}>
               <div className={`p-3 rounded-lg max-w-[85%] text-sm ${msg.role === 'user' ? 'bg-[#7C3AED] text-white' : 'bg-white/10 text-gray-200'}`}>
                 {msg.content}
               </div>
               {msg.options && msg.options.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {msg.options.map((opt: any, idx: number) => (
                      <button 
                        key={idx} 
                        onClick={() => handleOptionSelect(opt, msg.type)}
                        className="px-4 py-2 bg-[#7C3AED]/20 hover:bg-[#7C3AED]/40 border border-[#7C3AED]/30 text-[#A78BFA] rounded-lg text-xs transition"
                      >
                        {opt.label || opt.name || 'Select'}
                      </button>
                    ))}
                  </div>
               )}
             </div>
          ))}
          {loading && <div className="text-sm text-purple-400 animate-pulse">AI is thinking...</div>}
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-white/10 bg-[#0B0F19]">
          <div className="relative flex items-center">
            <input 
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="E.g., Change the navbar color to blue..."
              className="w-full bg-white/5 border border-white/10 rounded-full py-3 pl-4 pr-12 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            />
            <button onClick={() => handleSend()} className="absolute right-2 p-2 bg-purple-600 rounded-full text-white hover:bg-purple-700 transition">
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT PANE: LIVE PREVIEW */}
      <div className={isFullscreen ? "fixed inset-0 z-[100] flex flex-col bg-[#050505]" : "flex-1 flex flex-col bg-[#050505] relative"}>
        {/* Preview Toolbar */}
        <div className="h-14 border-b border-white/10 flex items-center justify-end px-6 bg-[#0B0F19]">
          <div className="flex items-center gap-3">
            <button onClick={() => setIsFullscreen(!isFullscreen)} className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors" title={isFullscreen ? "Minimize" : "Maximize"}>
              {isFullscreen ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
            </button>
            {generatedSiteData && (
              <button onClick={handleDownloadZip} className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-lg shadow-blue-500/20">
                <Download className="w-4 h-4" /> Download ZIP
              </button>
            )}
            <button className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-white bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 rounded-lg transition shadow-lg shadow-purple-500/20">
              <CheckCircle2 className="w-4 h-4" /> Finalize Website
            </button>
          </div>
        </div>

        {/* Live Website Canvas */}
        <div className="flex-1 overflow-auto p-8 flex items-center justify-center custom-scrollbar">
          {generatedSiteData ? (
             <div className="w-full h-full bg-white rounded-lg shadow-2xl overflow-hidden border border-gray-800">
               <iframe srcDoc={generateHtmlFromJSON(generatedSiteData)} className="w-full h-full bg-white" title="Website Preview" />
             </div>
          ) : (
             <div className="text-center text-gray-500 flex flex-col items-center">
               <Globe className="w-16 h-16 text-gray-700 mb-4" />
               <h3 className="text-lg font-medium text-gray-400">No Website Generated Yet</h3>
               <p className="text-sm mt-2 max-w-sm">Chat with the AI on the left to provide your business details and generate your first draft.</p>
             </div>
          )}
        </div>
      </div>
    </div>
  );
}
