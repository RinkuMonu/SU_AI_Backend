"use client";

import { useState } from "react";
import Link from "next/link";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authService } from "@/services/auth.service";
import { useAuth } from "@/components/auth/AuthProvider";
import { Card, CardContent } from "@/components/ui/card";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/ui/Logo";

const signupSchema = z.object({
  business_logo: z.string().optional(),
  brand_color: z.string().optional(),
  business_name: z.string().min(2, { message: "Business Name is required" }),
  business_type: z.string().min(1, { message: "Business Type is required" }),
  business_category: z.string().min(1, { message: "Business Category is required" }),
  sub_category: z.string().optional(),
  business_description: z.string().optional(),
  tagline: z.string().optional(),
  registration_number: z.string().optional(),
  year_established: z.string().optional(),
  number_of_employees: z.string().optional(),
  country: z.string().min(2, { message: "Country is required" }),
  state: z.string().min(2, { message: "State is required" }),
  city: z.string().min(2, { message: "City is required" }),
  area: z.string().optional(),
  pincode: z.string().optional(),
  full_address: z.string().optional(),
  google_maps_url: z.string().optional(),
  business_model: z.string().optional(),
  selling_model: z.string().optional(),
  target_age_group: z.array(z.string()).optional(),
  target_gender: z.string().optional(),
  target_location: z.string().optional(),
  customer_type: z.string().optional(),
  email: z.string().email({ message: "Invalid email address" }),
  password: z
    .string()
    .min(1, { message: "Password is required" }),
  confirmPassword: z.string()
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
});

type SignupFormValues = z.infer<typeof signupSchema>;

export default function SignupPage() {
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<SignupFormValues>({
    resolver: zodResolver(signupSchema),
    mode: "onChange",
  });

  const passwordValue = useWatch({
    control,
    name: "password",
    defaultValue: "",
  });

  const confirmPasswordValue = useWatch({
    control,
    name: "confirmPassword",
    defaultValue: "",
  });



  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [isGeneratingLogo, setIsGeneratingLogo] = useState(false);
  const [logoPrompt, setLogoPrompt] = useState("");
  const [logoColor, setLogoColor] = useState("#000000");

  const handleGenerateLogo = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!logoPrompt) return;
    setIsGeneratingLogo(true);
    try {
      const colorText = logoColor ? `using a ${logoColor} color scheme` : "";
      const fullPrompt = `${logoPrompt} ${colorText} professional business logo minimalist`;
      const url = `https://image.pollinations.ai/prompt/${encodeURIComponent(fullPrompt)}?width=512&height=512&nologo=true`;
      setLogoPreview(url);
    } catch (err) {
      console.error(err);
    } finally {
      setIsGeneratingLogo(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setLogoPreview(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  const onSubmit = async (data: SignupFormValues) => {
    setIsLoading(true);
    setError("");
    try {
      const payload = {
        ...data,
        business_logo: logoPreview || undefined,
        brand_color: logoColor || undefined,
        name: data.business_name,
        role: "business"
      };
      const response = await authService.signup(payload);
      if (response.token && response.user) {
        localStorage.setItem("access_token", response.token);
        localStorage.setItem("user", JSON.stringify(response.user));
        window.location.href = "/dashboard";
      } else {
        router.push("/login/user");
      }
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 py-10 bg-background">
      <div className="w-full max-w-3xl space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="flex flex-col items-center justify-center space-y-4 text-center">
          <Logo withText={false} className="scale-125 mb-4" />
          <h1 className="text-3xl font-bold tracking-tight text-white">Create an account</h1>
          <p className="text-sm text-text-muted">
            Start growing your business with AI Marketing
          </p>
        </div>

        <Card className="bg-card shadow-lg border-border">
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-4 pt-2 pb-4">
                <h3 className="text-lg font-medium text-white border-b border-border pb-2">Business Information</h3>

                <div className="space-y-4 mb-6 border border-border rounded-lg p-4 bg-black/20">
                  <h4 className="text-sm font-medium text-white mb-2">Business Logo</h4>
                  <div className="flex flex-col md:flex-row gap-6 items-start">
                    <div className="w-32 h-32 rounded-lg border-2 border-dashed border-border flex flex-col items-center justify-center overflow-hidden bg-background relative shrink-0">
                      {logoPreview ? (
                        <img src={logoPreview} alt="Logo Preview" className="w-full h-full object-cover" />
                      ) : (
                        <div className="text-xs text-text-muted text-center p-2">No Logo</div>
                      )}
                    </div>
                    <div className="flex-1 space-y-4 w-full">
                      <div className="space-y-2">
                        <Label>Option 1: Upload Logo</Label>
                        <Input type="file" accept="image/*" onChange={handleFileUpload} className="cursor-pointer file:text-white" />
                      </div>
                      <div className="text-xs text-text-muted text-center uppercase relative">
                        <span className="bg-card px-2 relative z-10">OR</span>
                        <div className="absolute top-1/2 left-0 w-full h-px bg-border -translate-y-1/2"></div>
                      </div>
                      <div className="space-y-2">
                        <Label>Option 2: Generate with AI</Label>
                        <div className="flex gap-2 items-center">
                          <Input 
                            type="color"
                            value={logoColor}
                            onChange={(e) => setLogoColor(e.target.value)}
                            className="w-12 h-10 p-1 shrink-0 cursor-pointer"
                            title="Brand Color"
                          />
                          <Input 
                            placeholder="Describe your logo (e.g., A minimalist tech icon)" 
                            value={logoPrompt}
                            onChange={(e) => setLogoPrompt(e.target.value)}
                          />
                          <Button onClick={handleGenerateLogo} disabled={isGeneratingLogo || !logoPrompt} type="button" variant="secondary" className="whitespace-nowrap shrink-0">
                            {isGeneratingLogo ? <Loader2 className="w-4 h-4 animate-spin" /> : "Generate"}
                          </Button>
                        </div>
                      </div>
                      {logoPreview && (
                        <div className="pt-2">
                          <a href={logoPreview} download="business_logo.png" target="_blank" rel="noreferrer">
                            <Button type="button" variant="outline" size="sm" className="w-full">Download Logo</Button>
                          </a>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="business_name">Business Name *</Label>
                  <Input id="business_name" placeholder="Your Business Name" {...register("business_name")} className={errors.business_name ? "border-red-500" : ""} />
                  {errors.business_name && <p className="text-xs text-red-500">{errors.business_name.message as string}</p>}
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="business_type">Business Type *</Label>
                    <Input id="business_type" placeholder="e.g., Retail, SaaS" {...register("business_type")} className={errors.business_type ? "border-red-500" : ""} />
                    {errors.business_type && <p className="text-xs text-red-500">{errors.business_type.message as string}</p>}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="business_category">Category *</Label>
                    <Input id="business_category" placeholder="e.g., Technology" {...register("business_category")} className={errors.business_category ? "border-red-500" : ""} />
                    {errors.business_category && <p className="text-xs text-red-500">{errors.business_category.message as string}</p>}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="sub_category">Sub-category</Label>
                    <Input id="sub_category" placeholder="Optional" {...register("sub_category")} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="year_established">Year Established</Label>
                    <Input id="year_established" placeholder="e.g., 2020" {...register("year_established")} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="business_description">Business Description</Label>
                  <Input id="business_description" placeholder="Short description" {...register("business_description")} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="tagline">Tagline / Slogan</Label>
                    <Input id="tagline" placeholder="Optional" {...register("tagline")} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="registration_number">Registration Number</Label>
                    <Input id="registration_number" placeholder="Optional" {...register("registration_number")} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="number_of_employees">Number of Employees</Label>
                  <Input id="number_of_employees" placeholder="Optional" {...register("number_of_employees")} />
                </div>
              </div>

              <div className="space-y-4 pt-2 pb-4">
                <h3 className="text-lg font-medium text-white border-b border-border pb-2">Account Details</h3>
                <div className="space-y-2">
                  <Label htmlFor="email">Email *</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="name@example.com"
                    {...register("email")}
                    className={errors.email ? "border-red-500" : ""}
                  />
                  {errors.email && (
                    <p className="text-xs text-red-500">{errors.email.message as string}</p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="password">Password *</Label>
                    <Input
                      id="password"
                      type="password"
                      {...register("password")}
                      className={errors.password ? "border-red-500" : ""}
                    />
                    {errors.password && (
                      <p className="text-xs text-red-500">{errors.password.message as string}</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="confirmPassword">Confirm Password *</Label>
                    <Input
                      id="confirmPassword"
                      type="password"
                      {...register("confirmPassword")}
                      className={errors.confirmPassword ? "border-red-500" : ""}
                    />
                    {errors.confirmPassword && (
                      <p className="text-xs text-red-500">{errors.confirmPassword.message as string}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-4 pt-2 pb-4">
                <h3 className="text-lg font-medium text-white border-b border-border pb-2">Business Location</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="country">Country *</Label>
                    <Input id="country" placeholder="e.g., India" {...register("country")} className={errors.country ? "border-red-500" : ""} />
                    {errors.country && <p className="text-xs text-red-500">{errors.country.message as string}</p>}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="state">State *</Label>
                    <Input id="state" placeholder="e.g., Maharashtra" {...register("state")} className={errors.state ? "border-red-500" : ""} />
                    {errors.state && <p className="text-xs text-red-500">{errors.state.message as string}</p>}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="city">City *</Label>
                    <Input id="city" placeholder="e.g., Mumbai" {...register("city")} className={errors.city ? "border-red-500" : ""} />
                    {errors.city && <p className="text-xs text-red-500">{errors.city.message as string}</p>}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="pincode">Pincode</Label>
                    <Input id="pincode" placeholder="e.g., 400001" {...register("pincode")} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="area">Area / Locality</Label>
                    <Input id="area" placeholder="Locality" {...register("area")} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="full_address">Full Address</Label>
                    <Input id="full_address" placeholder="Full Address" {...register("full_address")} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="google_maps_url">Google Maps / Place URL</Label>
                  <Input id="google_maps_url" placeholder="https://maps.google.com/..." {...register("google_maps_url")} />
                </div>
              </div>

              <div className="space-y-4 pt-2 pb-4">
                <h3 className="text-lg font-medium text-white border-b border-border pb-2">Business Type & Category</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="business_model">Business Model</Label>
                    <select id="business_model" {...register("business_model")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                      <option value="">Select Model</option>
                      <option value="Physical Store">Physical Store</option>
                      <option value="Online Business">Online Business</option>
                      <option value="Home Business">Home Business</option>
                      <option value="Service Business">Service Business</option>
                      <option value="Both Online & Offline">Both Online & Offline</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="selling_model">Selling Model</Label>
                    <select id="selling_model" {...register("selling_model")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                      <option value="">Select Selling Model</option>
                      <option value="Products">Products</option>
                      <option value="Services">Services</option>
                      <option value="Products + Services">Products + Services</option>
                    </select>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="business_category">Business Category</Label>
                  <select id="business_category" {...register("business_category")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                    <option value="">Select Category</option>
                    <option value="Fashion & Clothing">Fashion & Clothing</option>
                    <option value="Beauty & Salon">Beauty & Salon</option>
                    <option value="Restaurant / Cafe">Restaurant / Cafe</option>
                    <option value="Grocery">Grocery</option>
                    <option value="Electronics">Electronics</option>
                    <option value="Education">Education</option>
                    <option value="Healthcare">Healthcare</option>
                    <option value="Fitness">Fitness</option>
                    <option value="Real Estate">Real Estate</option>
                    <option value="Travel">Travel</option>
                    <option value="Jewellery">Jewellery</option>
                    <option value="Home & Furniture">Home & Furniture</option>
                    <option value="Automobile">Automobile</option>
                    <option value="Photography">Photography</option>
                    <option value="Professional Services">Professional Services</option>
                    <option value="Local Services">Local Services</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
              </div>

              <div className="space-y-4 pt-2 pb-4">
                <h3 className="text-lg font-medium text-white border-b border-border pb-2">Target Audience</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Age Group</Label>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                      {['13–18', '18–25', '25–35', '35–50', '50+'].map(age => (
                        <label key={age} className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" value={age} {...register("target_age_group")} className="accent-brand-purple" />
                          <span className="text-sm text-white">{age}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="target_gender">Gender</Label>
                      <select id="target_gender" {...register("target_gender")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                        <option value="">Select Gender</option>
                        <option value="Male">Male</option>
                        <option value="Female">Female</option>
                        <option value="All">All</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="customer_type">Customer Type</Label>
                      <select id="customer_type" {...register("customer_type")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                        <option value="">Select Customer Type</option>
                        <option value="B2C">B2C</option>
                        <option value="B2B">B2B</option>
                        <option value="Both">Both</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="target_location">Location Focus</Label>
                      <select id="target_location" {...register("target_location")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-white">
                        <option value="">Select Location</option>
                        <option value="Local">Local</option>
                        <option value="City">City</option>
                        <option value="State">State</option>
                        <option value="India">India</option>
                        <option value="International">International</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>


              {error && <div className="p-3 text-sm text-red-500 bg-red-500/10 border border-red-500/20 rounded-md">{error}</div>}

              <Button type="submit" className="w-full h-11 text-base" disabled={isLoading}>
                {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Create Account"}
              </Button>
            </form>
          </CardContent>
        </Card>
        
        <div className="text-center text-sm text-text-muted mt-6 pb-6">
          Already have an account?{" "}
          <Link href="/login/user" className="text-brand-pink font-medium hover:underline">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}

