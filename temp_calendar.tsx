"use client";

import { useEffect, useState } from "react";
import festivalService from "@/services/festival.service";
import { generateCalendar, DayPlan } from "@/services/calendar.service";
import { Loader2, Wand2, ChevronDown, ChevronUp, Play, Minus, Plus } from "lucide-react";

function FestiveCalendar({ plan }: { plan?: DayPlan[] | null }) {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [festivals, setFestivals] = useState<any[]>([]);

  useEffect(() => {
    festivalService.getUpcoming().then((data) => {
      const mapped = data.upcoming_festivals.map((f: any) => {
        const d = new Date(f.date);
        return {
          date: d.getDate(),
          month: d.getMonth(),
          name: f.name,
          type: 'festival'
        };
      });
      setFestivals(mapped);
    }).catch(console.error);
  }, []);

  const currentMonth = currentDate.getMonth();
  const currentYear = currentDate.getFullYear();
  const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
  const firstDayOfMonth = new Date(currentYear, currentMonth, 1).getDay();
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);
  const paddingDays = Array.from({ length: firstDayOfMonth }, (_, i) => i);
  const weekDays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const prevMonthDays = new Date(currentYear, currentMonth, 0).getDate();

  const handlePrevMonth = () => setCurrentDate(new Date(currentYear, currentMonth - 1, 1));
  const handleNextMonth = () => setCurrentDate(new Date(currentYear, currentMonth + 1, 1));

  const handleAddEvent = (defaultDate?: number) => {
    const name = window.prompt("Enter event name:");
    if (!name) return;
    const type = window.prompt("Event type (festival/occasion):", "occasion");
    const dateInput = defaultDate || window.prompt("Enter date number (1-31):");
    const dateNum = parseInt(dateInput as string);
    if (!isNaN(dateNum) && dateNum >= 1 && dateNum <= 31) {
      setFestivals([...festivals, { date: dateNum, month: currentMonth, name, type: type || 'occasion' }]);
    }
  };

  const currentMonthFestivals = festivals.filter(f => f.month === currentMonth && f.year === currentYear);

  return (
    <div className="w-full flex flex-col xl:flex-row gap-6 bg-[#121212] rounded-3xl p-6 shadow-2xl border border-white/5">
      {/* Calendar Grid */}
      <div className="flex-1">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <h2 className="text-3xl font-bold text-white tracking-tight">
              {currentDate.toLocaleDateString('en-US', { month: 'long' })} <span className="text-brand-purple">{currentYear}</span>
            </h2>
          </div>
          <div className="flex gap-2">
            <button onClick={handlePrevMonth} className="p-2 rounded-xl hover:bg-white/10 text-white/60 hover:text-white transition-colors bg-white/5 border border-white/10">
              <ChevronUp className="w-5 h-5 -rotate-90" />
            </button>
            <button onClick={handleNextMonth} className="p-2 rounded-xl hover:bg-white/10 text-white/60 hover:text-white transition-colors bg-white/5 border border-white/10">
              <ChevronDown className="w-5 h-5 -rotate-90" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-y-4 gap-x-2 text-center">
          {weekDays.map(day => (
            <div key={day} className="text-white/50 font-semibold text-sm uppercase tracking-wider pb-2 border-b border-white/10">
              {day}
            </div>
          ))}
          {paddingDays.map(day => (
            <div key={`padding-${day}`} className="flex items-center justify-center h-12 w-full text-sm text-white/20 font-medium">
              {prevMonthDays - paddingDays.length + day + 1}
            </div>
          ))}
          {days.map(day => {
            const isToday = new Date().getDate() === day && new Date().getMonth() === currentMonth && new Date().getFullYear() === currentYear;
            const hasPlan = plan && plan.find(p => p.day_number === day);
            const festival = currentMonthFestivals.find(f => f.date === day);
            
            return (
              <div key={day} className="relative flex items-center justify-center h-12 w-full group">
                <button 
                  onClick={() => handleAddEvent(day)}
                  className={`flex items-center justify-center h-10 w-10 rounded-xl text-sm font-semibold transition-all cursor-pointer z-10 ${isToday ? 'bg-brand-purple text-white shadow-[0_0_15px_rgba(190,50,255,0.4)]' : 'text-white/90 hover:bg-white/10'} ${hasPlan && !isToday ? 'border border-brand-purple text-brand-purple' : ''} ${festival && !isToday ? 'bg-brand-coral/10 text-brand-coral border border-brand-coral/20' : ''}`}
                >
                  {day}
                </button>
                {festival && (
                  <div className="absolute -bottom-1 w-1 h-1 rounded-full bg-brand-coral" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Events Side Panel */}
      <div className="w-full xl:w-72 flex-shrink-0 bg-surface-elevated rounded-2xl p-5 border border-white/5">
        <h3 className="text-white font-bold text-lg mb-4 flex items-center gap-2">
          <Wand2 className="w-5 h-5 text-brand-coral" />
          Upcoming Events
        </h3>
        <div className="space-y-4 mt-6">
          {currentMonthFestivals.length === 0 && (
            <p className="text-white/40 text-sm text-center py-4">No events this month.</p>
          )}
          {currentMonthFestivals.map((fest, idx) => (
            <div key={idx} className="flex gap-4 items-start p-3 rounded-xl hover:bg-white/5 transition-colors cursor-pointer group">
              <div className={`flex flex-col items-center justify-center w-12 h-12 rounded-xl flex-shrink-0 font-bold text-lg ${fest.type === 'festival' ? 'bg-brand-coral/20 text-brand-coral' : 'bg-brand-purple/20 text-brand-purple'}`}>
                {fest.date}
              </div>
              <div>
                <p className="text-white font-medium group-hover:text-brand-purple transition-colors">{fest.name}</p>
                <p className="text-white/50 text-xs capitalize mt-1">{fest.type}</p>
              </div>
            </div>
          ))}
          <div className="pt-4 mt-2 border-t border-white/5">
             <button onClick={() => handleAddEvent()} className="w-full py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-semibold transition-colors flex items-center justify-center gap-2 active:scale-95">
               <Plus className="w-4 h-4" /> Add Custom Event
             </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DayCard({ day, initialProductImage }: { day: DayPlan, initialProductImage: string | null }) {
  const [currentImage, setCurrentImage] = useState<string | null>(initialProductImage);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleGenerateDesign = () => {
    setIsGenerating(true);
    const prompt = day.visual_direction || `${day.content_type} for a product. High quality commercial photo.`;
    if (day.content_type === 'Reel') {
      setCurrentImage(`https://www.w3schools.com/html/mov_bbb.mp4`);
    } else {
      setCurrentImage(`https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=1080&height=1080&nologo=true&seed=${Math.floor(Math.random() * 10000)}`);
    }
  };

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-lg flex flex-col md:flex-row gap-6 hover:border-brand-purple/50 transition-colors">
      
      {/* Left: Thumbnail/Placeholder */}
      <div className="w-full md:w-48 flex-shrink-0 flex flex-col gap-3">
        <div className="relative aspect-square rounded-xl bg-surface-elevated overflow-hidden border border-border group">
          {isGenerating ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-surface/80 backdrop-blur-sm z-10">
              <Loader2 className="w-8 h-8 text-brand-purple animate-spin mb-2" />
              <span className="text-xs font-semibold text-brand-purple animate-pulse">Generating...</span>
            </div>
          ) : null}
          
          {currentImage ? (
            currentImage.endsWith('.mp4') ? (
            <video src={currentImage} onLoadedData={() => setIsGenerating(false)} autoPlay loop muted className="object-cover w-full h-full opacity-90 transition-transform duration-500 group-hover:scale-105" />
          ) : (
            <img src={currentImage} onLoad={() => setIsGenerating(false)} alt="Product" className="object-cover w-full h-full opacity-90 transition-transform duration-500 group-hover:scale-105" />
          )
          ) : (
            <div className="w-full h-full bg-brand-gradient opacity-20" />
          )}
          
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <span className="bg-black/60 text-white text-xs font-bold px-3 py-1.5 rounded-full backdrop-blur-sm shadow-sm border border-white/20">
              {day.content_type}
            </span>
          </div>
        </div>
        
        <button 
          onClick={handleGenerateDesign}
          disabled={isGenerating}
          className="w-full text-sm font-semibold text-brand-purple bg-brand-purple/10 hover:bg-brand-purple/20 py-2 rounded-lg transition-colors border border-brand-purple/20 flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
        >
          <Wand2 className="w-4 h-4" />
          Generate Design
        </button>
      </div>
      
      {/* Right: Content details */}
      <div className="flex-1 space-y-4">
        <div className="flex items-center gap-3 border-b border-border pb-3">
          <div className="bg-brand-purple text-white text-sm font-bold w-10 h-10 rounded-lg flex items-center justify-center shadow-[0_0_10px_rgba(190,50,255,0.3)]">
            Day {day.day_number}
          </div>
          <h3 className="text-xl font-extrabold text-white">{day.content_type}</h3>
        </div>
        
        <div>
          <p className="text-xs font-bold text-text-muted uppercase tracking-wider mb-1">Visual Direction</p>
          <p className="text-sm text-text-secondary font-medium leading-relaxed">{day.visual_direction}</p>
        </div>

        <div className="bg-surface-elevated rounded-xl p-4 border border-border">
          <p className="text-xs font-bold text-brand-pink uppercase tracking-wider mb-2">Caption</p>
          <p className="text-text-secondary text-sm whitespace-pre-line">{day.caption}</p>
          <p className="text-brand-coral text-sm mt-3 font-semibold break-words">{day.hashtags}</p>
        </div>
      </div>
    </div>
  );
}

export default function AICalendarPage() {
  const [productImage, setProductImage] = useState<string | null>(null);
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<DayPlan[] | null>(null);

  return (
    <div className="mx-auto max-w-7xl p-6">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">AI Social Media Calendar</h1>
        <p className="mt-2 text-text-muted">Generate a full 30-day content plan instantly.</p>
      </div>

      <div className="w-full">
        {loading && (
          <div className="flex h-64 items-center justify-center rounded-2xl border border-border bg-surface shadow-lg">
            <div className="flex flex-col items-center gap-4">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-purple/20 border-t-brand-purple"></div>
              <p className="text-text-muted font-medium animate-pulse">Designing your strategy... this takes a few seconds.</p>
            </div>
          </div>
        )}

        {!loading && plan && (
          <div className="space-y-6">
            {plan.map((day) => (
              <DayCard key={day.day_number} day={day} initialProductImage={productImage} />
            ))}
          </div>
        )}

        {!loading && !plan && (
          <FestiveCalendar plan={plan} />
        )}
      </div>
    </div>
  );
}

