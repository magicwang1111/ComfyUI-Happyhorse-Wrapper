// Based on the ComfyUI animated video preview pattern.
import { app, ANIM_PREVIEW_WIDGET } from "../../../scripts/app.js";
import { createImageHost } from "../../../scripts/ui/imagePreview.js";

const BASE_SIZE = 768;

function setVideoDimensions(videoElement, width, height) {
    videoElement.style.width = `${width}px`;
    videoElement.style.height = `${height}px`;
}

function resizeVideoAspectRatio(videoElement, maxWidth, maxHeight) {
    const aspectRatio = videoElement.videoWidth / videoElement.videoHeight;
    let newWidth;
    let newHeight;

    if (videoElement.videoWidth / maxWidth > videoElement.videoHeight / maxHeight) {
        newWidth = maxWidth;
        newHeight = newWidth / aspectRatio;
    } else {
        newHeight = maxHeight;
        newWidth = newHeight * aspectRatio;
    }

    setVideoDimensions(videoElement, newWidth, newHeight);
}

function chainCallback(object, property, callback) {
    if (object == undefined) {
        console.error("Tried to add callback to non-existent object");
        return;
    }
    if (property in object) {
        const callbackOrig = object[property];
        object[property] = function () {
            const result = callbackOrig.apply(this, arguments);
            callback.apply(this, arguments);
            return result;
        };
    } else {
        object[property] = callback;
    }
}

function addVideoPreview(nodeType) {
    const createVideoNode = (url) => {
        return new Promise((resolve) => {
            const videoEl = document.createElement("video");
            videoEl.addEventListener("loadedmetadata", () => {
                videoEl.controls = false;
                videoEl.loop = true;
                videoEl.muted = true;
                resizeVideoAspectRatio(videoEl, BASE_SIZE, BASE_SIZE);
                resolve(videoEl);
            });
            videoEl.addEventListener("error", () => resolve());
            videoEl.src = url;
        });
    };

    nodeType.prototype.onDrawBackground = function () {
        if (this.flags.collapsed) return;

        const imageURLs = this.images ?? [];
        const imagesChanged = JSON.stringify(this.displayingImages) !== JSON.stringify(imageURLs);
        if (!imagesChanged) return;

        this.displayingImages = imageURLs;
        if (!imageURLs.length) {
            this.imgs = null;
            this.animatedImages = false;
            return;
        }

        Promise.all(imageURLs.map((url) => createVideoNode(url)))
            .then((imgs) => {
                this.imgs = imgs.filter(Boolean);
            })
            .then(() => {
                if (!this.imgs.length) return;

                this.animatedImages = true;
                this.size[0] = BASE_SIZE;
                this.size[1] = BASE_SIZE;

                const widgetIdx = this.widgets?.findIndex((w) => w.name === ANIM_PREVIEW_WIDGET);
                if (widgetIdx > -1) {
                    this.widgets[widgetIdx].options.host.updateImages(this.imgs);
                } else {
                    const host = createImageHost(this);
                    const widget = this.addDOMWidget(ANIM_PREVIEW_WIDGET, "img", host.el, {
                        host,
                        getHeight: host.getHeight,
                        onDraw: host.onDraw,
                        hideOnZoom: false,
                    });
                    widget.serializeValue = () => ({ height: BASE_SIZE });
                    widget.options.host.updateImages(this.imgs);
                }

                this.imgs.forEach((img) => {
                    if (img instanceof HTMLVideoElement) {
                        img.muted = true;
                        img.autoplay = true;
                        img.play();
                    }
                });
                this.setDirtyCanvas(true, true);
            });
    };

    chainCallback(nodeType.prototype, "onExecuted", function (message) {
        if (message?.video_url) {
            this.images = message.video_url;
            this.setDirtyCanvas(true);
        }
    });
}

app.registerExtension({
    name: "ComfyUIHappyhorseWrapperVideoPreview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ComfyUI-Happyhorse-Wrapper Preview Video") {
            return;
        }
        addVideoPreview(nodeType);
    },
});

