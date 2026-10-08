"use client";

import { useEffect, useState } from "react";

import ProductSelector from "@/components/ai/ProductSelector";
import PlatformSelector from "@/components/ai/PlatformSelector";
import ObjectiveSelector from "@/components/ai/ObjectiveSelector";
import GeneratedPostCard from "@/components/ai/GeneratedPostCard";
import { InsufficientCreditsAlert } from "@/components/ui/InsufficientCreditsAlert";

import { generatePost } from "@/services/content.service";
import { FashionService } from "@/services/fashion.service";

import type { GeneratedPost } from "@/types/content";

export default function AIPostPage() {

  const [products, setProducts] = useState<any[]>([]);
  const [productIds, setProductIds] = useState<string[]>([]);
  const [platform, setPlatform] = useState("instagram");
  const [objective, setObjective] = useState(
    "product_promotion"
  );

  const [language, setLanguage] = useState("English");

  const [loading, setLoading] = useState(false);

  const [generatedPost, setGeneratedPost] =
    useState<GeneratedPost | null>(null);

  const [hasInsufficientCredits, setHasInsufficientCredits] = useState(false);

  useEffect(() => {

    async function loadProducts() {
      try {
        const data = await FashionService.getProducts();
        setProducts(data);
        if (data.length > 0) {
          setProductIds([data[0].id]);
        }
      } catch (error) {
        console.error("Failed to load products", error);
      }
    }

    loadProducts();

  }, []);

  const handleGenerate = async () => {

    if (productIds.length === 0) {
      alert("Please select at least one product");
      return;
    }

    try {

      setLoading(true);
      setGeneratedPost(null);
      setHasInsufficientCredits(false);

      const result = await generatePost({
        product_id: productIds[0], // for backward compatibility
        product_ids: productIds,
        platform,
        objective,
        language,
      });

      setGeneratedPost(result);
      window.dispatchEvent(new Event("credit-update"));

    } catch (error: any) {

      console.error(
        "AI post generation failed:",
        error
      );

      if (error?.response?.status === 402 || error?.message?.toLowerCase().includes("credit")) {
        setHasInsufficientCredits(true);
      } else {
        alert(
          "Unable to generate post. Please try again."
        );
      }

    } finally {

      setLoading(false);

    }
  };

  return (
    <main className="py-10">

      <div className="max-w-6xl mx-auto px-4">

        <div className="mb-10">

          <h1 className="text-3xl font-bold text-white">
            AI Post Maker
          </h1>

          <p className="mt-2 text-text-muted">
            Create AI-powered marketing content
            using your Business, Brand Kit and Products.
          </p>

        </div>

        {hasInsufficientCredits && <InsufficientCreditsAlert />}

        <div className="space-y-8">

          <section className="rounded-2xl bg-surface border border-border p-6 shadow-lg">

            <h2 className="text-xl font-semibold mb-5 text-white">
              1. Select Product
            </h2>

            <ProductSelector
              products={products}
              value={productIds}
              onChange={setProductIds}
            />

            {productIds.length > 0 && (
              <div className="mt-6 p-4 bg-brand-purple/5 border border-brand-purple/20 rounded-xl">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="font-semibold text-brand-purple">Selected Products ({productIds.length})</h3>
                  <button onClick={() => setProductIds([])} className="text-xs text-text-muted hover:text-white transition">Remove All</button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {productIds.map(id => {
                    const p = products.find(prod => prod.id === id);
                    return p ? (
                      <div key={id} className="flex items-center gap-2 bg-surface border border-border px-3 py-1.5 rounded-full text-sm">
                        <svg className="w-3 h-3 text-green-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        {p.name}
                      </div>
                    ) : null;
                  })}
                </div>
              </div>
            )}

          </section>

          <section className="rounded-2xl bg-surface border border-border p-6 shadow-lg">

            <h2 className="text-xl font-semibold mb-5 text-white">
              2. Select Platform
            </h2>

            <PlatformSelector
              value={platform}
              onChange={setPlatform}
            />

          </section>

          <section className="rounded-2xl bg-surface border border-border p-6 shadow-lg">

            <h2 className="text-xl font-semibold mb-5 text-white">
              3. Select Objective
            </h2>

            <ObjectiveSelector
              value={objective}
              onChange={setObjective}
            />

          </section>

          <section className="rounded-2xl bg-surface border border-border p-6 shadow-lg">

            <button
              onClick={handleGenerate}
              disabled={loading}
              className="
                w-full rounded-xl
                bg-brand-gradient text-white
                px-6 py-4
                font-semibold
                disabled:opacity-50
                hover:opacity-90 transition-opacity
              "
            >
              {loading
                ? "Generating..."
                : "✨ Generate AI Post"}
            </button>

          </section>

          {generatedPost && (
            <GeneratedPostCard
              post={generatedPost}
              imageUrl={products.find(p => p.id === productId)?.image_url}
            />
          )}

        </div>

      </div>

    </main>
  );
}
