const test = require('node:test');
const assert = require('node:assert/strict');
const {descriptor,presentation} = require('../../operations/static/operations/map-markers.js');
const ring = [[31,121],[31.001,121],[31,121.001]];

test('automatic locations retain boundaries and use pins only when no boundary exists', () => {
    assert.equal(presentation({map_display:'auto'},[ring]).mode,'boundary');
    const point = presentation({kind:'building',latitude:'31',longitude:'121'},[]);
    assert.equal(point.mode,'pin');
    assert.deepEqual(point.center,[31,121]);
});

test('explicit pins do not discard boundary data and prefer their map anchor', () => {
    const location = {map_display:'pin',center:{lat:32,lng:122},latitude:31,longitude:121};
    assert.deepEqual(presentation(location,[ring]),{mode:'pin',center:[31,121]});
    assert.equal(presentation({map_display:'pin'},[ring]).mode,'pin');
    assert.equal(ring.length,3);
    assert.equal(location.center.lat,32);
});

test('no position remains unplaced instead of creating a misleading marker at zero', () => {
    for (const value of [undefined,null,'',' ',true,'bad',Infinity,91]) {
        assert.equal(presentation({latitude:value,longitude:121},[]).mode,'none');
    }
    assert.deepEqual(presentation({map_display:'pin',latitude:0,longitude:0},[]),{mode:'pin',center:[0,0]});
});

test('location types use distinct symbols and untrusted kinds fall back to a fixed style', () => {
    const kinds=['zone','building','floor','room','monitoring','other'];
    assert.equal(new Set(kinds.map(kind=>descriptor(kind).path)).size,kinds.length);
    assert.equal(descriptor('constructor'),descriptor('other'));
    assert.equal(descriptor('__proto__'),descriptor('other'));
    assert.equal(descriptor('<script>'),descriptor('other'));
});
