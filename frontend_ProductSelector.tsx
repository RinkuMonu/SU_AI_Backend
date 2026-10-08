"use client";

interface Product {
  id: string;
  name: string;
  image_url?: string;
}

interface ProductSelectorProps {
  products: Product[];
  value: string[];
  onChange: (ids: string[]) => void;
  maxSelection?: number;
}

export default function ProductSelector({
  products,
  value = [],
  onChange,
  maxSelection = 5,
}: ProductSelectorProps) {

  const handleSelect = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter(v => v !== id));
    } else {
      if (value.length < maxSelection) {
        onChange([...value, id]);
      } else {
        alert(`You can select up to ${maxSelection} products.`);
      }
    }
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {products.map((product) => {

        const selected = value.includes(product.id);

        return (
          <button
            key={product.id}
            type="button"
            onClick={() => handleSelect(product.id)}
            className={`
              relative rounded-xl border p-4 text-left
              transition
              ${
                selected
                  ? "border-brand-purple ring-2 ring-brand-purple/20 bg-brand-purple/5"
                  : "border-border hover:border-brand-purple/50 bg-surface"
              }
            `}
          >
            {selected && (
              <div className="absolute top-2 right-2 bg-brand-purple text-white rounded-full p-1 shadow-md">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
              </div>
            )}

            {product.image_url && (
              <img
                src={product.image_url}
                alt={product.name}
                className="w-full aspect-square object-cover rounded-lg mb-3"
              />
            )}

            <p className="font-medium">
              {product.name}
            </p>

          </button>
        );
      })}
    </div>
  );
}
