/*
 * Leaflet.ImageOverlay.Rotated — MIT License, © Iván Sánchez Ortega
 * https://github.com/IvanSanchez/Leaflet.ImageOverlay.Rotated
 * Positions an image using three control points (top-left, top-right,
 * bottom-left), enabling rotation and skew on a Leaflet map.
 */
L.ImageOverlay.Rotated = L.ImageOverlay.extend({

	initialize: function (image, topleft, topright, bottomleft, options) {

		if (typeof(image) === 'string') {
			this._url = image;
		} else {
			// Assume that the first parameter is an instance of HTMLImage or HTMLCanvas
			this._rawImage = image;
		}

		this._topLeft    = L.latLng(topleft);
		this._topRight   = L.latLng(topright);
		this._bottomLeft = L.latLng(bottomleft);

		L.setOptions(this, options);
	},


	onAdd: function (map) {
		if (!this._image) {
			this._initImage();

			if (this.options.opacity < 1) {
				this._updateOpacity();
			}
		}

		if (this.options.interactive) {
			L.DomUtil.addClass(this._rawImage, 'leaflet-interactive');
			this.addInteractiveTarget(this._rawImage);
		}

		map.on('zoomend resetview', this._reset, this);

		this.getPane().appendChild(this._image);
		this._reset();
	},


    onRemove: function(map) {
        map.off('zoomend resetview', this._reset, this);
        L.ImageOverlay.prototype.onRemove.call(this, map);
    },


	_initImage: function () {
		var img = this._rawImage;
		if (this._url) {
			img = L.DomUtil.create('img');
			img.style.display = 'none';	// Hide while the first transform (zero or one frames) is being done

			if (this.options.crossOrigin) {
				img.crossOrigin = '';
			}

			// Assign the URL after installing load and error handlers.
			this._rawImage = img;
		}
		L.DomUtil.addClass(img, 'leaflet-image-layer');

		// this._image is reused by some of the methods of the parent class and
		// must keep the name, even if it is counter-intuitive.
		var div = this._image = L.DomUtil.create('div',
				'leaflet-image-layer ' + (this._zoomAnimated ? 'leaflet-zoom-animated' : ''));

		this._updateZIndex(); // apply z-index style setting to the div (if defined)

		div.appendChild(img);

		div.onselectstart = L.Util.falseFn;
		div.onmousemove = L.Util.falseFn;

		img.onload = function(){
			this._reset();
			img.style.display = 'block';
			this.fire('load');
		}.bind(this);

		img.alt = this.options.alt || '';
        img.style.maxWidth = 'none';
        img.style.maxHeight = 'none';
        img.onerror = () => this.fire('error');
        if (this._url) img.src = this._url;
	},


	_reset: function () {
		var div = this._image;

		if (!this._map) {
			return;
		}

		// Project control points to container-pixel coordinates
		var pxTopLeft    = this._map.latLngToLayerPoint(this._topLeft);
		var pxTopRight   = this._map.latLngToLayerPoint(this._topRight);
		var pxBottomLeft = this._map.latLngToLayerPoint(this._bottomLeft);

		// Infer coordinate of bottom right
		var pxBottomRight = pxTopRight.subtract(pxTopLeft).add(pxBottomLeft);

		// pxBounds is mostly for positioning the <div> container
		var pxBounds = L.bounds([pxTopLeft, pxTopRight, pxBottomLeft, pxBottomRight]);
		var size = pxBounds.getSize();
		var pxTopLeftInDiv = pxTopLeft.subtract(pxBounds.min);

		// LatLngBounds are needed for (zoom) animations
		this._bounds = L.latLngBounds( this._map.layerPointToLatLng(pxBounds.min),
		                               this._map.layerPointToLatLng(pxBounds.max) );

		L.DomUtil.setPosition(div, pxBounds.min);

		div.style.width  = size.x + 'px';
		div.style.height = size.y + 'px';

		var imgW = this._rawImage.naturalWidth || this._rawImage.width;
		var imgH = this._rawImage.naturalHeight || this._rawImage.height;
		if (!imgW || !imgH) {
			return;	// Probably because the image hasn't loaded yet.
		}

		// Sides of the control-point box, in pixels
		// These are the main ingredient for the transformation matrix.
		var vectorX = pxTopRight.subtract(pxTopLeft);
		var vectorY = pxBottomLeft.subtract(pxTopLeft);

		this._rawImage.style.transformOrigin = '0 0';

		// The transformation is an affine matrix that switches
		// coordinates around in just the right way. This is the result
		// of calculating the skew/rotation/scale matrices and simplyfing
		// everything.
		this._rawImage.style.transform = "matrix(" +
			(vectorX.x/imgW) + ', ' + (vectorX.y/imgW) + ', ' +
			(vectorY.x/imgH) + ', ' + (vectorY.y/imgH) + ', ' +
			pxTopLeftInDiv.x + ', ' + pxTopLeftInDiv.y + ')';

	},


	reposition: function(topleft, topright, bottomleft) {
		this._topLeft    = L.latLng(topleft);
		this._topRight   = L.latLng(topright);
		this._bottomLeft = L.latLng(bottomleft);
		this._reset();
	},


	setUrl: function (url) {
		this._url = url;

		if (this._rawImage) {
			this._rawImage.src = url;
		}
		return this;
	}
});

/* Instantiates a rotated/skewed image overlay, given the image URL and
 * the `LatLng`s of three of its corners.
 */
L.imageOverlay.rotated = function(imgSrc, topleft, topright, bottomleft, options) {
	return new L.ImageOverlay.Rotated(imgSrc, topleft, topright, bottomleft, options);
};
