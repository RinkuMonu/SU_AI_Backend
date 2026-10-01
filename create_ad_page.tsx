"use client";

import { useState, useEffect } from "react";
import { Loader2, CheckCircle2, Share2 } from "lucide-react";

import { getProducts } from "@/services/product.service";
import { Product } from "@/types/product";


import { useCreateAd } from "@/hooks/useCreateAd";

export default function CreateAdPage() {

  const [productId, setProductId] =
    useState("");

  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    const fetchProducts = async () => {
      try {
        const data = await getProducts();
        setProducts(data);
      } catch (err) {
        console.error("Failed to load products");
      }
    };
    fetchProducts();
  }, []);

  const [prompt, setPrompt] = useState("");

  const {
    create,
    loading,
    result,
    error,
  } = useCreateAd();

  const handleGenerate = async () => {

    await create({
      product_id: productId,
      prompt: prompt,
    });

  };

  const [isPublishingFacebook, setIsPublishingFacebook] = useState(false);
  const [isPublishingInstagram, setIsPublishingInstagram] = useState(false);
  const [publishSuccessMessage, setPublishSuccessMessage] = useState<string | null>(null);

  const handlePublish = async (publishPlatform: 'facebook' | 'instagram') => {
    if (publishPlatform === 'facebook') setIsPublishingFacebook(true);
    else setIsPublishingInstagram(true);
    
    setPublishSuccessMessage(null);
    
    try {
      const token = localStorage.getItem('token');
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const res = await fetch(`${baseUrl}/api/v1/social/publish-${publishPlatform}/${result?.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      if (!res.ok) throw new Error('Publish failed');
      
      setPublishSuccessMessage(`Successfully Published to ${publishPlatform.charAt(0).toUpperCase() + publishPlatform.slice(1)}!`);
      setTimeout(() => setPublishSuccessMessage(null), 5000);
    } catch (err) {
      console.error(err);
      alert('Failed to publish. Please ensure you have linked your account.');
    } finally {
      if (publishPlatform === 'facebook') setIsPublishingFacebook(false);
      else setIsPublishingInstagram(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-6">

      <div className="mb-8">

        <h1 className="text-3xl font-bold text-white">
          Create Ad
        </h1>

        <p className="mt-2 text-text-muted">
          Generate AI-powered advertising creatives.
        </p>

      </div>

      <div className="grid gap-8 lg:grid-cols-3">

        <div className="space-y-6 rounded-2xl border border-border bg-surface p-6 lg:col-span-2 shadow-lg">

          {/* Product */}

          <div>

            <label className="mb-2 block font-semibold text-white">
              Product
            </label>

            <select
              value={productId}
              onChange={(e) =>
                setProductId(e.target.value)
              }
              className="w-full rounded-lg border border-border bg-surface-elevated text-white p-3 focus:ring-2 focus:ring-brand-purple outline-none"
            >
              <option value="">Select a Product</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>

          </div>

          <div>
            <label className="mb-2 block font-semibold text-white">
              Ad Prompt
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the ad you want to generate in detail..."
              className="min-h-[200px] w-full rounded-lg border border-border bg-surface-elevated text-white p-4 focus:ring-2 focus:ring-brand-purple outline-none resize-none"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-4 text-red-400">
              {error}
            </div>
          )}

          <button
            disabled={loading}
            onClick={handleGenerate}
            className="w-full rounded-xl bg-brand-gradient hover:opacity-90 transition-opacity px-6 py-4 font-semibold text-white disabled:opacity-50"
          >
            {loading
              ? "Generating Ad..."
              : "Generate Ad"}
          </button>

        </div>

        {/* Preview */}

        <div className="rounded-2xl border border-border bg-surface p-6 shadow-lg">

          <h2 className="mb-5 text-xl font-bold text-white">
            Ad Preview
          </h2>

          {result ? (

            <div className="space-y-5">

              <img
                src={result.creative_url}
                alt="AI Ad"
                className="w-full rounded-xl"
              />

              <h3 className="text-xl font-bold text-white">
                {result.headline}
              </h3>

              <p className="text-text-secondary">
                {result.primary_text}
              </p>

              <p className="text-text-muted">
                {result.description}
              </p>

              <a 
                href={productId ? `/products/${productId}` : "/products"}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-center w-full rounded-lg bg-brand-gradient p-3 font-semibold text-white hover:opacity-90 transition-opacity active:scale-[0.98]"
              >
                {result.cta}
              </a>

              <div className="flex flex-wrap gap-2">

                {result.hashtags?.map(
                  (tag: string) => (

                    <span
                      key={tag}
                      className="rounded-full bg-surface-elevated px-3 py-1 text-sm text-text-muted"
                    >
                      #{tag.replace("#", "")}
                    </span>

                  )
                )}

              </div>

              <div className="pt-4 mt-4 border-t border-border">
                {publishSuccessMessage ? (
                  <div className="w-full rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 p-4 text-center font-semibold flex items-center justify-center gap-2">
                    <CheckCircle2 className="w-5 h-5" /> {publishSuccessMessage}
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 mt-2">
                    <button 
                      onClick={() => handlePublish('instagram')}
                      disabled={isPublishingInstagram || isPublishingFacebook}
                      className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#833ab4] via-[#fd1d1d] to-[#fcb045] hover:opacity-90 transition-opacity px-4 py-3 font-bold text-white shadow-md disabled:opacity-50"
                    >
                      {isPublishingInstagram ? <Loader2 className="w-5 h-5 animate-spin" /> : <Share2 className="w-5 h-5" />}
                      {isPublishingInstagram ? 'Publishing...' : `Publish to Instagram`}
                    </button>

                    <button 
                      onClick={() => handlePublish('facebook')}
                      disabled={isPublishingFacebook || isPublishingInstagram}
                      className="w-full flex items-center justify-center gap-2 rounded-xl bg-[#1877F2] hover:bg-[#166fe5] transition-colors px-4 py-3 font-bold text-white shadow-md disabled:opacity-50"
                    >
                      {isPublishingFacebook ? <Loader2 className="w-5 h-5 animate-spin" /> : <Share2 className="w-5 h-5" />}
                      {isPublishingFacebook ? 'Publishing...' : `Publish to Facebook`}
                    </button>
                  </div>
                )}
              </div>

            </div>

          ) : productId && products.find(p => p.id === productId) ? (
            
            <div className="space-y-5">
              {(() => {
                const selected = products.find(p => p.id === productId);
                const imageUrl = selected?.image_url || (selected?.images && selected.images[0]) || "";
                return (
                  <>
                    {imageUrl && (
                      <img
                        src={imageUrl}
                        alt={selected?.name}
                        className="w-full rounded-xl"
                      />
                    )}
                    <h3 className="text-xl font-bold text-white">
                      {selected?.name}
                    </h3>
                    <p className="text-text-secondary">
                      {selected?.description || "Product description..."}
                    </p>
                    <a 
                      href={`/products/${selected?.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block text-center w-full rounded-lg bg-brand-gradient p-3 font-semibold text-white hover:opacity-90 transition-opacity active:scale-[0.98]"
                    >
                      {"Shop Now"}
                    </a>
                  </>
                );
              })()}
            </div>
            
          ) : (

            <div className="flex min-h-[400px] items-center justify-center text-center text-text-muted">
              Your generated ad will appear here.
            </div>

          )}

        </div>

      </div>

    </div>
  );
}
