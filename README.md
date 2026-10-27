# Print & Pin · Poster Print

[한국어 설명](README.ko.md)

## Introduction video

[![Print & Pin introduction video](https://i.ytimg.com/vi/AwLWuNOE6Js/hqdefault.jpg)](https://youtu.be/AwLWuNOE6Js)

[Watch: I Made 2 Blender Add-ons That Turn Images Into a Poster Wall | Print & Pin](https://youtu.be/AwLWuNOE6Js)

Create textured poster planes in Blender from images, with cropping, atlas layouts, paper effects, and photo borders.

Poster Print is part of **Print & Pin**. It can be used on its own or together with **[Poster Pin](https://github.com/didle4037-star/poster-pin)**: Poster Print creates the source posters, and Poster Pin arranges them in the scene.

## Features

- Import images and cut image sheets into individual images.
- Arrange images in an atlas and build poster planes with matching UVs and materials.
- Add photo borders, instant-photo formats, captions, and photo-strip layouts.
- Apply paper textures, color treatments, wear, holes, tears, and crumple effects.
- Re-edit previously built poster batches.
- Pass the resulting source collection to Poster Pin when both add-ons are enabled.

## Version and compatibility

- Author: **G_ni**
- Version in the add-on metadata: **1.81.0**
- Minimum Blender version declared by the package: **5.2.0**
- UI languages: **English / 한국어**

The declared Blender version is taken from the source metadata; it is not a compatibility test report.

## Installation

1. Open this repository's **Releases** and download **`Poster_Print_v1.81.zip`**.
2. In Blender, open **Edit → Preferences → Add-ons** and choose **Install from Disk** from the menu.
3. Select the downloaded file and enable **Print & Pin · Poster Print**.
4. In the 3D Viewport, press **N** to open the sidebar and choose **Poster Print**.

This release uses the legacy add-on format. Use the attached installation archive rather than assuming GitHub's automatically generated source ZIP is the installation package.

## Quick start

1. In **Poster Print**, choose an output folder.
2. Use **Add Images** to add the images you want to work with.
3. Open **Layout Editor · Build** to arrange the images and adjust their appearance.
4. Use **Apply · Build Posters** to generate the poster batch.
5. Use the posters in your scene, or link their collection to Poster Pin for placement.

## Optional Substance workflow

The **Bake from Substance File** feature uses Substance Designer command-line tools (`sbsrender`, and `sbscooker` for `.sbs` inputs). Configure the tool location and an extra paper texture folder to use it. The package also includes pre-baked paper textures.

## Feedback

Please use this repository's **Issues** for bugs and suggestions. Include the add-on version, Blender version, operating system, reproduction steps, and any error message. Screenshots or a small example file are helpful when relevant.


This is a personal project, so replies and fixes may take some time. Thank you for your patience!
