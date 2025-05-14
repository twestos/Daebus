// @ts-check
import { defineConfig, passthroughImageService } from "astro/config";
import starlight from "@astrojs/starlight";

// https://astro.build/config
export default defineConfig({
	integrations: [
		starlight({
			title: "Daebus",
			social: [
				{
					icon: "github",
					label: "GitHub",
					href: "https://github.com/twestos/Daebus",
				},
			],
			sidebar: [
                {
                    label: "Overview",
                    slug: "overview"
                },
                {
                    label: "Installation",
                    slug: "installation"
                },
                {
                    label: "Getting Started",
                    slug: "getting-started"
                },
				{
					label: "Guides",
					autogenerate: { directory: "guides" },
				},
			],
		}),
	],
	image: {
		service: passthroughImageService(),
	},
});
