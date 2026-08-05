import{A as e,D as t,F as n,J as r,M as i,N as a,O as o,S as s,T as c,Y as l,at as u,c as d,i as f,m as p,ot as m,s as h,ut as g,z as _}from"./warn-Cq0iJHZk.js";import{n as v,t as y}from"./runtime-dom.esm-bundler-GD5ae1WU.js";import{B as b,I as x,J as S,K as C,N as w,P as T,R as E,U as D,W as O,Y as k,a as A,et as j,i as M,n as N,o as P,q as F,s as I,z as L}from"./Icon-CIeviPh2.js";function ee(e,t){if(e===void 0)return!1;if(t){let{context:{ids:n}}=t;return n.has(e)}return j(e)!==null}function R(e){let t=p(e),n=m(t.value);return r(t,e=>{n.value=e}),typeof e==`function`?n:{__v_isRef:!0,get value(){return n.value},set value(t){e.set(t)}}}function te(){let e=m(!1);return n(()=>{e.value=!0}),u(e)}var z=typeof document<`u`&&typeof window<`u`;function B(e){return e.replace(/#|\(|\)|,|\s|\./g,`_`)}function V(e,...t){if(Array.isArray(e))e.forEach(e=>V(e,...t));else return e(...t)}function H(e){return e.some(e=>o(e)?!(e.type===h||e.type===d&&!H(e.children)):!0)?e:null}function ne(e,t){return e&&H(e())||t()}function re(e,t,n){return e&&H(e(t))||n(t)}function U(e,t){return t(e&&H(e())||null)}function W(e){return!(e&&H(e()))}var G=f(`n-form-item`);function K(e,{defaultSize:n=`medium`,mergedSize:r,mergedDisabled:i}={}){let o=t(G,null);_(G,null);let s=p(r?()=>r(o):()=>{let{size:t}=e;if(t)return t;if(o){let{mergedSize:e}=o;if(e.value!==void 0)return e.value}return n}),c=p(i?()=>i(o):()=>{let{disabled:t}=e;return t===void 0?o?o.disabled.value:!1:t}),l=p(()=>{let{status:t}=e;return t||o?.mergedValidationStatus.value});return a(()=>{o&&o.restoreValidation()}),{mergedSizeRef:s,mergedDisabledRef:c,mergedStatusRef:l,nTriggerFormBlur(){o&&o.handleContentBlur()},nTriggerFormChange(){o&&o.handleContentChange()},nTriggerFormFocus(){o&&o.handleContentFocus()},nTriggerFormInput(){o&&o.handleContentInput()}}}function ie(e,n,r){if(!n)return;let a=E(),o=p(()=>{let{value:t}=n;if(!t)return;let r=t[e];if(r)return r}),s=t(x,null),c=()=>{l(()=>{let{value:t}=r,n=`${t}${e}Rtl`;if(ee(n,a))return;let{value:i}=o;i&&i.style.mount({id:n,head:!0,anchorMetaName:I,props:{bPrefix:t?`.${t}-`:void 0},ssr:a,parent:s?.styleMountTarget})})};return a?c():i(c),o}function q(e,n,r){if(!n)return;let a=E(),o=t(x,null),s=()=>{let t=r.value;n.mount({id:t===void 0?e:t+e,head:!0,anchorMetaName:I,props:{bPrefix:t?`.${t}-`:void 0},ssr:a,parent:o?.styleMountTarget}),o?.preflightStyleDisabled||A.mount({id:`n-global`,head:!0,anchorMetaName:I,ssr:a,parent:o?.styleMountTarget})};a?s():i(s)}var J=s({name:`BaseIconSwitchTransition`,setup(e,{slots:t}){let n=te();return()=>c(y,{name:`icon-switch-transition`,appear:n.value},t)}}),{cubicBezierEaseInOut:ae}=P;function Y({originalTransform:e=``,left:t=0,top:n=0,transition:r=`all .3s ${ae} !important`}={}){return[D(`&.icon-switch-transition-enter-from, &.icon-switch-transition-leave-to`,{transform:`${e} scale(0.75)`,left:t,top:n,opacity:0}),D(`&.icon-switch-transition-enter-to, &.icon-switch-transition-leave-from`,{transform:`scale(1) ${e}`,left:t,top:n,opacity:1}),D(`&.icon-switch-transition-enter-active, &.icon-switch-transition-leave-active`,{transformOrigin:`center`,position:`absolute`,left:t,top:n,transition:r})]}var oe=s({name:`FadeInExpandTransition`,props:{appear:Boolean,group:Boolean,mode:String,onLeave:Function,onAfterLeave:Function,onAfterEnter:Function,width:Boolean,reverse:Boolean},setup(e,{slots:t}){function n(t){e.width?t.style.maxWidth=`${t.offsetWidth}px`:t.style.maxHeight=`${t.offsetHeight}px`,t.offsetWidth}function r(t){e.width?t.style.maxWidth=`0`:t.style.maxHeight=`0`,t.offsetWidth;let{onLeave:n}=e;n&&n()}function i(t){e.width?t.style.maxWidth=``:t.style.maxHeight=``;let{onAfterLeave:n}=e;n&&n()}function a(t){if(t.style.transition=`none`,e.width){let e=t.offsetWidth;t.style.maxWidth=`0`,t.offsetWidth,t.style.transition=``,t.style.maxWidth=`${e}px`}else if(e.reverse)t.style.maxHeight=`${t.offsetHeight}px`,t.offsetHeight,t.style.transition=``,t.style.maxHeight=`0`;else{let e=t.offsetHeight;t.style.maxHeight=`0`,t.offsetWidth,t.style.transition=``,t.style.maxHeight=`${e}px`}t.offsetWidth}function o(t){var n;e.width?t.style.maxWidth=``:e.reverse||(t.style.maxHeight=``),(n=e.onAfterEnter)==null||n.call(e)}return()=>{let{group:s,width:l,appear:u,mode:d}=e,f=s?v:y,p={name:l?`fade-in-width-expand-transition`:`fade-in-height-expand-transition`,appear:u,onEnter:a,onAfterEnter:o,onBeforeLeave:n,onLeave:r,onAfterLeave:i};return s||(p.mode=d),c(f,p,t)}}}),se=D([D(`@keyframes rotator`,`
 0% {
 -webkit-transform: rotate(0deg);
 transform: rotate(0deg);
 }
 100% {
 -webkit-transform: rotate(360deg);
 transform: rotate(360deg);
 }`),O(`base-loading`,`
 position: relative;
 line-height: 0;
 width: 1em;
 height: 1em;
 `,[C(`transition-wrapper`,`
 position: absolute;
 width: 100%;
 height: 100%;
 `,[Y()]),C(`placeholder`,`
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 `,[Y({left:`50%`,top:`50%`,originalTransform:`translateX(-50%) translateY(-50%)`})]),C(`container`,`
 animation: rotator 3s linear infinite both;
 `,[C(`icon`,`
 height: 1em;
 width: 1em;
 `)])])]),X=`1.6s`,ce={strokeWidth:{type:Number,default:28},stroke:{type:String,default:void 0},scale:{type:Number,default:1},radius:{type:Number,default:100}},le=s({name:`BaseLoading`,props:Object.assign({clsPrefix:{type:String,required:!0},show:{type:Boolean,default:!0}},ce),setup(e){q(`-base-loading`,se,g(e,`clsPrefix`))},render(){let{clsPrefix:e,radius:t,strokeWidth:n,stroke:r,scale:i}=this,a=t/i;return c(`div`,{class:`${e}-base-loading`,role:`img`,"aria-label":`loading`},c(J,null,{default:()=>this.show?c(`div`,{key:`icon`,class:`${e}-base-loading__transition-wrapper`},c(`div`,{class:`${e}-base-loading__container`},c(`svg`,{class:`${e}-base-loading__icon`,viewBox:`0 0 ${2*a} ${2*a}`,xmlns:`http://www.w3.org/2000/svg`,style:{color:r}},c(`g`,null,c(`animateTransform`,{attributeName:`transform`,type:`rotate`,values:`0 ${a} ${a};270 ${a} ${a}`,begin:`0s`,dur:X,fill:`freeze`,repeatCount:`indefinite`}),c(`circle`,{class:`${e}-base-loading__icon`,fill:`none`,stroke:`currentColor`,"stroke-width":n,"stroke-linecap":`round`,cx:a,cy:a,r:t-n/2,"stroke-dasharray":5.67*t,"stroke-dashoffset":18.48*t},c(`animateTransform`,{attributeName:`transform`,type:`rotate`,values:`0 ${a} ${a};135 ${a} ${a};450 ${a} ${a}`,begin:`0s`,dur:X,fill:`freeze`,repeatCount:`indefinite`}),c(`animate`,{attributeName:`stroke-dashoffset`,values:`${5.67*t};${1.42*t};${5.67*t}`,begin:`0s`,dur:X,fill:`freeze`,repeatCount:`indefinite`})))))):c(`div`,{key:`placeholder`,class:`${e}-base-loading__placeholder`},this.$slots)}))}}),{cubicBezierEaseInOut:Z}=P;function ue({duration:e=`.2s`,delay:t=`.1s`}={}){return[D(`&.fade-in-width-expand-transition-leave-from, &.fade-in-width-expand-transition-enter-to`,{opacity:1}),D(`&.fade-in-width-expand-transition-leave-to, &.fade-in-width-expand-transition-enter-from`,`
 opacity: 0!important;
 margin-left: 0!important;
 margin-right: 0!important;
 `),D(`&.fade-in-width-expand-transition-leave-active`,`
 overflow: hidden;
 transition:
 opacity ${e} ${Z},
 max-width ${e} ${Z} ${t},
 margin-left ${e} ${Z} ${t},
 margin-right ${e} ${Z} ${t};
 `),D(`&.fade-in-width-expand-transition-enter-active`,`
 overflow: hidden;
 transition:
 opacity ${e} ${Z} ${t},
 max-width ${e} ${Z},
 margin-left ${e} ${Z},
 margin-right ${e} ${Z};
 `)]}var de=O(`base-wave`,`
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border-radius: inherit;
`),fe=s({name:`BaseWave`,props:{clsPrefix:{type:String,required:!0}},setup(t){q(`-base-wave`,de,g(t,`clsPrefix`));let n=m(null),r=m(!1),i=null;return a(()=>{i!==null&&window.clearTimeout(i)}),{active:r,selfRef:n,play(){i!==null&&(window.clearTimeout(i),r.value=!1,i=null),e(()=>{var e;(e=n.value)==null||e.offsetHeight,r.value=!0,i=window.setTimeout(()=>{r.value=!1,i=null},1e3)})}}},render(){let{clsPrefix:e}=this;return c(`div`,{ref:`selfRef`,"aria-hidden":!0,class:[`${e}-base-wave`,this.active&&`${e}-base-wave--active`]})}}),pe=z&&`chrome`in window;z&&navigator.userAgent.includes(`Firefox`);var me=z&&navigator.userAgent.includes(`Safari`)&&!pe;function Q(e){return b(e,[255,255,255,.16])}function $(e){return b(e,[0,0,0,.12])}var he=f(`n-button-group`),ge={paddingTiny:`0 6px`,paddingSmall:`0 10px`,paddingMedium:`0 14px`,paddingLarge:`0 18px`,paddingRoundTiny:`0 10px`,paddingRoundSmall:`0 14px`,paddingRoundMedium:`0 18px`,paddingRoundLarge:`0 22px`,iconMarginTiny:`6px`,iconMarginSmall:`6px`,iconMarginMedium:`6px`,iconMarginLarge:`6px`,iconSizeTiny:`14px`,iconSizeSmall:`18px`,iconSizeMedium:`18px`,iconSizeLarge:`20px`,rippleDuration:`.6s`};function _e(e){let{heightTiny:t,heightSmall:n,heightMedium:r,heightLarge:i,borderRadius:a,fontSizeTiny:o,fontSizeSmall:s,fontSizeMedium:c,fontSizeLarge:l,opacityDisabled:u,textColor2:d,textColor3:f,primaryColorHover:p,primaryColorPressed:m,borderColor:h,primaryColor:g,baseColor:_,infoColor:v,infoColorHover:y,infoColorPressed:b,successColor:x,successColorHover:S,successColorPressed:C,warningColor:w,warningColorHover:T,warningColorPressed:E,errorColor:D,errorColorHover:O,errorColorPressed:k,fontWeight:A,buttonColor2:j,buttonColor2Hover:M,buttonColor2Pressed:N,fontWeightStrong:P}=e;return Object.assign(Object.assign({},ge),{heightTiny:t,heightSmall:n,heightMedium:r,heightLarge:i,borderRadiusTiny:a,borderRadiusSmall:a,borderRadiusMedium:a,borderRadiusLarge:a,fontSizeTiny:o,fontSizeSmall:s,fontSizeMedium:c,fontSizeLarge:l,opacityDisabled:u,colorOpacitySecondary:`0.16`,colorOpacitySecondaryHover:`0.22`,colorOpacitySecondaryPressed:`0.28`,colorSecondary:j,colorSecondaryHover:M,colorSecondaryPressed:N,colorTertiary:j,colorTertiaryHover:M,colorTertiaryPressed:N,colorQuaternary:`#0000`,colorQuaternaryHover:M,colorQuaternaryPressed:N,color:`#0000`,colorHover:`#0000`,colorPressed:`#0000`,colorFocus:`#0000`,colorDisabled:`#0000`,textColor:d,textColorTertiary:f,textColorHover:p,textColorPressed:m,textColorFocus:p,textColorDisabled:d,textColorText:d,textColorTextHover:p,textColorTextPressed:m,textColorTextFocus:p,textColorTextDisabled:d,textColorGhost:d,textColorGhostHover:p,textColorGhostPressed:m,textColorGhostFocus:p,textColorGhostDisabled:d,border:`1px solid ${h}`,borderHover:`1px solid ${p}`,borderPressed:`1px solid ${m}`,borderFocus:`1px solid ${p}`,borderDisabled:`1px solid ${h}`,rippleColor:g,colorPrimary:g,colorHoverPrimary:p,colorPressedPrimary:m,colorFocusPrimary:p,colorDisabledPrimary:g,textColorPrimary:_,textColorHoverPrimary:_,textColorPressedPrimary:_,textColorFocusPrimary:_,textColorDisabledPrimary:_,textColorTextPrimary:g,textColorTextHoverPrimary:p,textColorTextPressedPrimary:m,textColorTextFocusPrimary:p,textColorTextDisabledPrimary:d,textColorGhostPrimary:g,textColorGhostHoverPrimary:p,textColorGhostPressedPrimary:m,textColorGhostFocusPrimary:p,textColorGhostDisabledPrimary:g,borderPrimary:`1px solid ${g}`,borderHoverPrimary:`1px solid ${p}`,borderPressedPrimary:`1px solid ${m}`,borderFocusPrimary:`1px solid ${p}`,borderDisabledPrimary:`1px solid ${g}`,rippleColorPrimary:g,colorInfo:v,colorHoverInfo:y,colorPressedInfo:b,colorFocusInfo:y,colorDisabledInfo:v,textColorInfo:_,textColorHoverInfo:_,textColorPressedInfo:_,textColorFocusInfo:_,textColorDisabledInfo:_,textColorTextInfo:v,textColorTextHoverInfo:y,textColorTextPressedInfo:b,textColorTextFocusInfo:y,textColorTextDisabledInfo:d,textColorGhostInfo:v,textColorGhostHoverInfo:y,textColorGhostPressedInfo:b,textColorGhostFocusInfo:y,textColorGhostDisabledInfo:v,borderInfo:`1px solid ${v}`,borderHoverInfo:`1px solid ${y}`,borderPressedInfo:`1px solid ${b}`,borderFocusInfo:`1px solid ${y}`,borderDisabledInfo:`1px solid ${v}`,rippleColorInfo:v,colorSuccess:x,colorHoverSuccess:S,colorPressedSuccess:C,colorFocusSuccess:S,colorDisabledSuccess:x,textColorSuccess:_,textColorHoverSuccess:_,textColorPressedSuccess:_,textColorFocusSuccess:_,textColorDisabledSuccess:_,textColorTextSuccess:x,textColorTextHoverSuccess:S,textColorTextPressedSuccess:C,textColorTextFocusSuccess:S,textColorTextDisabledSuccess:d,textColorGhostSuccess:x,textColorGhostHoverSuccess:S,textColorGhostPressedSuccess:C,textColorGhostFocusSuccess:S,textColorGhostDisabledSuccess:x,borderSuccess:`1px solid ${x}`,borderHoverSuccess:`1px solid ${S}`,borderPressedSuccess:`1px solid ${C}`,borderFocusSuccess:`1px solid ${S}`,borderDisabledSuccess:`1px solid ${x}`,rippleColorSuccess:x,colorWarning:w,colorHoverWarning:T,colorPressedWarning:E,colorFocusWarning:T,colorDisabledWarning:w,textColorWarning:_,textColorHoverWarning:_,textColorPressedWarning:_,textColorFocusWarning:_,textColorDisabledWarning:_,textColorTextWarning:w,textColorTextHoverWarning:T,textColorTextPressedWarning:E,textColorTextFocusWarning:T,textColorTextDisabledWarning:d,textColorGhostWarning:w,textColorGhostHoverWarning:T,textColorGhostPressedWarning:E,textColorGhostFocusWarning:T,textColorGhostDisabledWarning:w,borderWarning:`1px solid ${w}`,borderHoverWarning:`1px solid ${T}`,borderPressedWarning:`1px solid ${E}`,borderFocusWarning:`1px solid ${T}`,borderDisabledWarning:`1px solid ${w}`,rippleColorWarning:w,colorError:D,colorHoverError:O,colorPressedError:k,colorFocusError:O,colorDisabledError:D,textColorError:_,textColorHoverError:_,textColorPressedError:_,textColorFocusError:_,textColorDisabledError:_,textColorTextError:D,textColorTextHoverError:O,textColorTextPressedError:k,textColorTextFocusError:O,textColorTextDisabledError:d,textColorGhostError:D,textColorGhostHoverError:O,textColorGhostPressedError:k,textColorGhostFocusError:O,textColorGhostDisabledError:D,borderError:`1px solid ${D}`,borderHoverError:`1px solid ${O}`,borderPressedError:`1px solid ${k}`,borderFocusError:`1px solid ${O}`,borderDisabledError:`1px solid ${D}`,rippleColorError:D,waveOpacity:`0.6`,fontWeight:A,fontWeightStrong:P})}var ve={name:`Button`,common:N,self:_e},ye=D([O(`button`,`
 margin: 0;
 font-weight: var(--n-font-weight);
 line-height: 1;
 font-family: inherit;
 padding: var(--n-padding);
 height: var(--n-height);
 font-size: var(--n-font-size);
 border-radius: var(--n-border-radius);
 color: var(--n-text-color);
 background-color: var(--n-color);
 width: var(--n-width);
 white-space: nowrap;
 outline: none;
 position: relative;
 z-index: auto;
 border: none;
 display: inline-flex;
 flex-wrap: nowrap;
 flex-shrink: 0;
 align-items: center;
 justify-content: center;
 user-select: none;
 -webkit-user-select: none;
 text-align: center;
 cursor: pointer;
 text-decoration: none;
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 opacity .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[F(`color`,[C(`border`,{borderColor:`var(--n-border-color)`}),F(`disabled`,[C(`border`,{borderColor:`var(--n-border-color-disabled)`})]),S(`disabled`,[D(`&:focus`,[C(`state-border`,{borderColor:`var(--n-border-color-focus)`})]),D(`&:hover`,[C(`state-border`,{borderColor:`var(--n-border-color-hover)`})]),D(`&:active`,[C(`state-border`,{borderColor:`var(--n-border-color-pressed)`})]),F(`pressed`,[C(`state-border`,{borderColor:`var(--n-border-color-pressed)`})])])]),F(`disabled`,{backgroundColor:`var(--n-color-disabled)`,color:`var(--n-text-color-disabled)`},[C(`border`,{border:`var(--n-border-disabled)`})]),S(`disabled`,[D(`&:focus`,{backgroundColor:`var(--n-color-focus)`,color:`var(--n-text-color-focus)`},[C(`state-border`,{border:`var(--n-border-focus)`})]),D(`&:hover`,{backgroundColor:`var(--n-color-hover)`,color:`var(--n-text-color-hover)`},[C(`state-border`,{border:`var(--n-border-hover)`})]),D(`&:active`,{backgroundColor:`var(--n-color-pressed)`,color:`var(--n-text-color-pressed)`},[C(`state-border`,{border:`var(--n-border-pressed)`})]),F(`pressed`,{backgroundColor:`var(--n-color-pressed)`,color:`var(--n-text-color-pressed)`},[C(`state-border`,{border:`var(--n-border-pressed)`})])]),F(`loading`,`cursor: wait;`),O(`base-wave`,`
 pointer-events: none;
 top: 0;
 right: 0;
 bottom: 0;
 left: 0;
 animation-iteration-count: 1;
 animation-duration: var(--n-ripple-duration);
 animation-timing-function: var(--n-bezier-ease-out), var(--n-bezier-ease-out);
 `,[F(`active`,{zIndex:1,animationName:`button-wave-spread, button-wave-opacity`})]),z&&`MozBoxSizing`in document.createElement(`div`).style?D(`&::moz-focus-inner`,{border:0}):null,C(`border, state-border`,`
 position: absolute;
 left: 0;
 top: 0;
 right: 0;
 bottom: 0;
 border-radius: inherit;
 transition: border-color .3s var(--n-bezier);
 pointer-events: none;
 `),C(`border`,`
 border: var(--n-border);
 `),C(`state-border`,`
 border: var(--n-border);
 border-color: #0000;
 z-index: 1;
 `),C(`icon`,`
 margin: var(--n-icon-margin);
 margin-left: 0;
 height: var(--n-icon-size);
 width: var(--n-icon-size);
 max-width: var(--n-icon-size);
 font-size: var(--n-icon-size);
 position: relative;
 flex-shrink: 0;
 `,[O(`icon-slot`,`
 height: var(--n-icon-size);
 width: var(--n-icon-size);
 position: absolute;
 left: 0;
 top: 50%;
 transform: translateY(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 `,[Y({top:`50%`,originalTransform:`translateY(-50%)`})]),ue()]),C(`content`,`
 display: flex;
 align-items: center;
 flex-wrap: nowrap;
 min-width: 0;
 `,[D(`~`,[C(`icon`,{margin:`var(--n-icon-margin)`,marginRight:0})])]),F(`block`,`
 display: flex;
 width: 100%;
 `),F(`dashed`,[C(`border, state-border`,{borderStyle:`dashed !important`})]),F(`disabled`,{cursor:`not-allowed`,opacity:`var(--n-opacity-disabled)`})]),D(`@keyframes button-wave-spread`,{from:{boxShadow:`0 0 0.5px 0 var(--n-ripple-color)`},to:{boxShadow:`0 0 0.5px 4.5px var(--n-ripple-color)`}}),D(`@keyframes button-wave-opacity`,{from:{opacity:`var(--n-wave-opacity)`},to:{opacity:0}})]),be=s({name:`Button`,props:Object.assign(Object.assign({},M.props),{color:String,textColor:String,text:Boolean,block:Boolean,loading:Boolean,disabled:Boolean,circle:Boolean,size:String,ghost:Boolean,round:Boolean,secondary:Boolean,tertiary:Boolean,quaternary:Boolean,strong:Boolean,focusable:{type:Boolean,default:!0},keyboard:{type:Boolean,default:!0},tag:{type:String,default:`button`},type:{type:String,default:`default`},dashed:Boolean,renderIcon:Function,iconPlacement:{type:String,default:`left`},attrType:{type:String,default:`button`},bordered:{type:Boolean,default:!0},onClick:[Function,Array],nativeFocusBehavior:{type:Boolean,default:!me},spinProps:Object}),slots:Object,setup(e){let n=m(null),r=m(null),i=m(!1),a=R(()=>!e.quaternary&&!e.tertiary&&!e.secondary&&!e.text&&(!e.color||e.ghost||e.dashed)&&e.bordered),o=t(he,{}),{inlineThemeDisabled:s,mergedClsPrefixRef:c,mergedRtlRef:l,mergedComponentPropsRef:u}=T(e),{mergedSizeRef:d}=K({},{defaultSize:`medium`,mergedSize:t=>{let{size:n}=e;if(n)return n;let{size:r}=o;if(r)return r;let{mergedSize:i}=t||{};return i?i.value:u?.value?.Button?.size||`medium`}}),f=p(()=>e.focusable&&!e.disabled),h=t=>{var r;f.value||t.preventDefault(),!e.nativeFocusBehavior&&(t.preventDefault(),!e.disabled&&f.value&&((r=n.value)==null||r.focus({preventScroll:!0})))},g=t=>{var n;if(!e.disabled&&!e.loading){let{onClick:i}=e;i&&V(i,t),e.text||(n=r.value)==null||n.play()}},_=t=>{switch(t.key){case`Enter`:if(!e.keyboard)return;i.value=!1}},v=t=>{switch(t.key){case`Enter`:if(!e.keyboard||e.loading){t.preventDefault();return}i.value=!0}},y=()=>{i.value=!1},b=M(`Button`,`-button`,ye,ve,e,c),x=ie(`Button`,l,c),S=p(()=>{let{common:{cubicBezierEaseInOut:t,cubicBezierEaseOut:n},self:r}=b.value,{rippleDuration:i,opacityDisabled:a,fontWeight:o,fontWeightStrong:s}=r,c=d.value,{dashed:l,type:u,ghost:f,text:p,color:m,round:h,circle:g,textColor:_,secondary:v,tertiary:y,quaternary:x,strong:S}=e,C={"--n-font-weight":S?s:o},w={"--n-color":`initial`,"--n-color-hover":`initial`,"--n-color-pressed":`initial`,"--n-color-focus":`initial`,"--n-color-disabled":`initial`,"--n-ripple-color":`initial`,"--n-text-color":`initial`,"--n-text-color-hover":`initial`,"--n-text-color-pressed":`initial`,"--n-text-color-focus":`initial`,"--n-text-color-disabled":`initial`},T=u===`tertiary`,E=u==="default",D=T?`default`:u;if(p){let e=_||m;w={"--n-color":`#0000`,"--n-color-hover":`#0000`,"--n-color-pressed":`#0000`,"--n-color-focus":`#0000`,"--n-color-disabled":`#0000`,"--n-ripple-color":`#0000`,"--n-text-color":e||r[k(`textColorText`,D)],"--n-text-color-hover":e?Q(e):r[k(`textColorTextHover`,D)],"--n-text-color-pressed":e?$(e):r[k(`textColorTextPressed`,D)],"--n-text-color-focus":e?Q(e):r[k(`textColorTextHover`,D)],"--n-text-color-disabled":e||r[k(`textColorTextDisabled`,D)]}}else if(f||l){let e=_||m;w={"--n-color":`#0000`,"--n-color-hover":`#0000`,"--n-color-pressed":`#0000`,"--n-color-focus":`#0000`,"--n-color-disabled":`#0000`,"--n-ripple-color":m||r[k(`rippleColor`,D)],"--n-text-color":e||r[k(`textColorGhost`,D)],"--n-text-color-hover":e?Q(e):r[k(`textColorGhostHover`,D)],"--n-text-color-pressed":e?$(e):r[k(`textColorGhostPressed`,D)],"--n-text-color-focus":e?Q(e):r[k(`textColorGhostHover`,D)],"--n-text-color-disabled":e||r[k(`textColorGhostDisabled`,D)]}}else if(v){let e=E?r.textColor:T?r.textColorTertiary:r[k(`color`,D)],t=m||e,n=u!=="default"&&u!==`tertiary`;w={"--n-color":n?L(t,{alpha:Number(r.colorOpacitySecondary)}):r.colorSecondary,"--n-color-hover":n?L(t,{alpha:Number(r.colorOpacitySecondaryHover)}):r.colorSecondaryHover,"--n-color-pressed":n?L(t,{alpha:Number(r.colorOpacitySecondaryPressed)}):r.colorSecondaryPressed,"--n-color-focus":n?L(t,{alpha:Number(r.colorOpacitySecondaryHover)}):r.colorSecondaryHover,"--n-color-disabled":r.colorSecondary,"--n-ripple-color":`#0000`,"--n-text-color":t,"--n-text-color-hover":t,"--n-text-color-pressed":t,"--n-text-color-focus":t,"--n-text-color-disabled":t}}else if(y||x){let e=E?r.textColor:T?r.textColorTertiary:r[k(`color`,D)],t=m||e;y?(w[`--n-color`]=r.colorTertiary,w[`--n-color-hover`]=r.colorTertiaryHover,w[`--n-color-pressed`]=r.colorTertiaryPressed,w[`--n-color-focus`]=r.colorSecondaryHover,w[`--n-color-disabled`]=r.colorTertiary):(w[`--n-color`]=r.colorQuaternary,w[`--n-color-hover`]=r.colorQuaternaryHover,w[`--n-color-pressed`]=r.colorQuaternaryPressed,w[`--n-color-focus`]=r.colorQuaternaryHover,w[`--n-color-disabled`]=r.colorQuaternary),w[`--n-ripple-color`]=`#0000`,w[`--n-text-color`]=t,w[`--n-text-color-hover`]=t,w[`--n-text-color-pressed`]=t,w[`--n-text-color-focus`]=t,w[`--n-text-color-disabled`]=t}else w={"--n-color":m||r[k(`color`,D)],"--n-color-hover":m?Q(m):r[k(`colorHover`,D)],"--n-color-pressed":m?$(m):r[k(`colorPressed`,D)],"--n-color-focus":m?Q(m):r[k(`colorFocus`,D)],"--n-color-disabled":m||r[k(`colorDisabled`,D)],"--n-ripple-color":m||r[k(`rippleColor`,D)],"--n-text-color":_||(m?r.textColorPrimary:T?r.textColorTertiary:r[k(`textColor`,D)]),"--n-text-color-hover":_||(m?r.textColorHoverPrimary:r[k(`textColorHover`,D)]),"--n-text-color-pressed":_||(m?r.textColorPressedPrimary:r[k(`textColorPressed`,D)]),"--n-text-color-focus":_||(m?r.textColorFocusPrimary:r[k(`textColorFocus`,D)]),"--n-text-color-disabled":_||(m?r.textColorDisabledPrimary:r[k(`textColorDisabled`,D)])};let O={"--n-border":`initial`,"--n-border-hover":`initial`,"--n-border-pressed":`initial`,"--n-border-focus":`initial`,"--n-border-disabled":`initial`};O=p?{"--n-border":`none`,"--n-border-hover":`none`,"--n-border-pressed":`none`,"--n-border-focus":`none`,"--n-border-disabled":`none`}:{"--n-border":r[k(`border`,D)],"--n-border-hover":r[k(`borderHover`,D)],"--n-border-pressed":r[k(`borderPressed`,D)],"--n-border-focus":r[k(`borderFocus`,D)],"--n-border-disabled":r[k(`borderDisabled`,D)]};let{[k(`height`,c)]:A,[k(`fontSize`,c)]:j,[k(`padding`,c)]:M,[k(`paddingRound`,c)]:N,[k(`iconSize`,c)]:P,[k(`borderRadius`,c)]:F,[k(`iconMargin`,c)]:I,waveOpacity:ee}=r,R={"--n-width":g&&!p?A:`initial`,"--n-height":p?`initial`:A,"--n-font-size":j,"--n-padding":g||p?`initial`:h?N:M,"--n-icon-size":P,"--n-icon-margin":I,"--n-border-radius":p?`initial`:g||h?A:F};return Object.assign(Object.assign(Object.assign(Object.assign({"--n-bezier":t,"--n-bezier-ease-out":n,"--n-ripple-duration":i,"--n-opacity-disabled":a,"--n-wave-opacity":ee},C),w),O),R)}),C=s?w(`button`,p(()=>{let t=``,{dashed:n,type:r,ghost:i,text:a,color:o,round:s,circle:c,textColor:l,secondary:u,tertiary:f,quaternary:p,strong:m}=e;n&&(t+=`a`),i&&(t+=`b`),a&&(t+=`c`),s&&(t+=`d`),c&&(t+=`e`),u&&(t+=`f`),f&&(t+=`g`),p&&(t+=`h`),m&&(t+=`i`),o&&(t+=`j${B(o)}`),l&&(t+=`k${B(l)}`);let{value:h}=d;return t+=`l${h[0]}`,t+=`m${r[0]}`,t}),S,e):void 0;return{selfElRef:n,waveElRef:r,mergedClsPrefix:c,mergedFocusable:f,mergedSize:d,showBorder:a,enterPressed:i,rtlEnabled:x,handleMousedown:h,handleKeydown:v,handleBlur:y,handleKeyup:_,handleClick:g,customColorCssVars:p(()=>{let{color:t}=e;if(!t)return null;let n=Q(t);return{"--n-border-color":t,"--n-border-color-hover":n,"--n-border-color-pressed":$(t),"--n-border-color-focus":n,"--n-border-color-disabled":t}}),cssVars:s?void 0:S,themeClass:C?.themeClass,onRender:C?.onRender}},render(){let{mergedClsPrefix:e,tag:t,onRender:n}=this;n?.();let r=U(this.$slots.default,t=>t&&c(`span`,{class:`${e}-button__content`},t));return c(t,{ref:`selfElRef`,class:[this.themeClass,`${e}-button`,`${e}-button--${this.type}-type`,`${e}-button--${this.mergedSize}-type`,this.rtlEnabled&&`${e}-button--rtl`,this.disabled&&`${e}-button--disabled`,this.block&&`${e}-button--block`,this.enterPressed&&`${e}-button--pressed`,!this.text&&this.dashed&&`${e}-button--dashed`,this.color&&`${e}-button--color`,this.secondary&&`${e}-button--secondary`,this.loading&&`${e}-button--loading`,this.ghost&&`${e}-button--ghost`],tabindex:this.mergedFocusable?0:-1,type:this.attrType,style:this.cssVars,disabled:this.disabled,onClick:this.handleClick,onBlur:this.handleBlur,onMousedown:this.handleMousedown,onKeyup:this.handleKeyup,onKeydown:this.handleKeydown},this.iconPlacement===`right`&&r,c(oe,{width:!0},{default:()=>U(this.$slots.icon,t=>(this.loading||this.renderIcon||t)&&c(`span`,{class:`${e}-button__icon`,style:{margin:W(this.$slots.default)?`0`:``}},c(J,null,{default:()=>this.loading?c(le,Object.assign({clsPrefix:e,key:`loading`,class:`${e}-icon-slot`,strokeWidth:20},this.spinProps)):c(`div`,{key:`icon`,class:`${e}-icon-slot`,role:`none`},this.renderIcon?this.renderIcon():t)})))}),this.iconPlacement===`left`&&r,this.text?null:c(fe,{ref:`waveElRef`,clsPrefix:e}),this.showBorder?c(`div`,{"aria-hidden":!0,class:`${e}-button__border`,style:this.customColorCssVars}):null,this.showBorder?c(`div`,{"aria-hidden":!0,class:`${e}-button__state-border`,style:this.customColorCssVars}):null)}}),xe=be;export{R as C,te as S,re as _,le as a,B as b,Y as c,ie as d,G as f,ne as g,W as h,me as i,J as l,H as m,xe as n,ce as o,K as p,ve as r,oe as s,be as t,q as u,U as v,z as x,V as y};