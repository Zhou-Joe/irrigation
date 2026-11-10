/* Pest selections reuse the irrigation work-order chip classes and form fields. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.FOSWorkorderChips = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function createState(tree) {
        const nodes = new Map(), parents = new Map(), selected = new Set();
        let trail = [];
        function copy(items, parent) {
            return items.map(item => {
                const id = String(item.id);
                if (nodes.has(id)) throw new Error('Duplicate work-content identifier');
                const node = {id, name: String(item.name), kind: item.kind, children: []};
                nodes.set(id, node);
                parents.set(id, parent);
                node.children = copy(item.children || [], id);
                return node;
            });
        }
        const roots = copy(tree, null);
        function path(id) {
            id = String(id);
            if (!nodes.has(id)) return [];
            const result = [];
            while (id !== null) {
                result.unshift(nodes.get(id));
                id = parents.get(id);
            }
            return result;
        }
        return {
            roots,
            path,
            branches: () => trail.map(id => nodes.get(id)),
            selected: () => [...selected].map(id => nodes.get(id)),
            isSelected: id => selected.has(String(id)),
            hasSelection: id => [...selected].some(leaf => path(leaf).some(node => node.id === String(id))),
            choose(id) {
                id = String(id);
                const node = nodes.get(id);
                if (!node) return false;
                const ancestry = path(id).map(item => item.id);
                if (node.children.length) trail = ancestry;
                else {
                    trail = ancestry.slice(0, -1);
                    if (selected.has(id)) selected.delete(id);
                    else selected.add(id);
                }
                return true;
            },
            remove: id => selected.delete(String(id)),
        };
    }

    function mount(form, tree, presetNodes = [], onChange = () => {}) {
        const doc = form.ownerDocument;
        const state = createState(tree);
        const categories = form.querySelector('#pestCategoryChips');
        const levels = form.querySelector('#pestWorkLevels');
        const summary = form.querySelector('#pestSelectedWork');
        function hidden(name, value) {
            const input = doc.createElement('input');
            input.type = 'hidden'; input.name = name; input.value = value;
            return input;
        }
        function chip(node) {
            const button = doc.createElement('button');
            button.type = 'button'; button.className = 'v2-chip';
            button.dataset.node = node.id; button.textContent = node.name;
            const active = state.isSelected(node.id) || state.branches().some(branch => branch.id === node.id);
            button.classList.toggle('active', active);
            button.classList.toggle('partial', !active && state.hasSelection(node.id));
            button.setAttribute('aria-pressed', String(active));
            button.onclick = () => {
                state.choose(node.id); render(); onChange();
                [...form.querySelectorAll('[data-node]')].find(item => item.dataset.node === node.id)?.focus({preventScroll:true});
            };
            return button;
        }
        function render() {
            categories.replaceChildren(...state.roots.map(chip));
            levels.replaceChildren();
            for (const parent of state.branches()) {
                const section = doc.createElement('div'); section.className = 'pest-chip-level';
                const label = doc.createElement('div'); label.className = 'v2-fl'; label.textContent = parent.name;
                const choices = doc.createElement('div'); choices.className = 'v2-chip-group';
                choices.append(...parent.children.map(chip)); section.append(label, choices); levels.append(section);
            }
            if (!state.branches().length) {
                const hint = doc.createElement('p'); hint.className = 'pest-chip-hint';
                hint.textContent = '先选择工作类别，再逐级选择工作内容。'; levels.append(hint);
            }
            summary.replaceChildren();
            if (state.selected().length) {
                const label = doc.createElement('div'); label.className = 'v2-fl';
                label.textContent = '已选内容 · ' + state.selected().length; summary.append(label);
                const list = doc.createElement('div'); list.className = 'v2-chip-group pest-chip-summary';
                for (const node of state.selected()) {
                    const name = state.path(node.id).map(item => item.name).join(' / ');
                    const button = doc.createElement('button');
                    button.type = 'button'; button.className = 'v2-chip active';
                    button.textContent = name + ' ×'; button.setAttribute('aria-label', '移除 ' + name);
                    button.onclick = () => {state.remove(node.id); render(); onChange();};
                    list.append(button, hidden('nodes', node.id));
                }
                summary.append(list);
            }
        }
        const shiftButtons = [...form.querySelectorAll('[data-shift]')];
        for (const button of shiftButtons) button.onclick = () => {
            form.elements.shift.value = button.dataset.shift;
            for (const item of shiftButtons) {
                const active = item === button;
                item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active));
            }
            onChange();
        };
        for (const id of presetNodes) state.choose(id);
        render();
        return state;
    }
    return {createState, mount};
});
