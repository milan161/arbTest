import{S as e,T as t,c as n,m as r}from"./warn-Cq0iJHZk.js";import{J as i,K as a,N as o,P as s,W as c,i as l,n as u,q as d}from"./Icon-CIeviPh2.js";function f(e){let{textColor1:t,dividerColor:n,fontWeightStrong:r}=e;return{textColor:t,color:n,fontWeight:r}}var p={name:`Divider`,common:u,self:f},m=c(`divider`,`
 position: relative;
 display: flex;
 width: 100%;
 box-sizing: border-box;
 font-size: 16px;
 color: var(--n-text-color);
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
`,[i(`vertical`,`
 margin-top: 24px;
 margin-bottom: 24px;
 `,[i(`no-title`,`
 display: flex;
 align-items: center;
 `)]),a(`title`,`
 display: flex;
 align-items: center;
 margin-left: 12px;
 margin-right: 12px;
 white-space: nowrap;
 font-weight: var(--n-font-weight);
 `),d(`title-position-left`,[a(`line`,[d(`left`,{width:`28px`})])]),d(`title-position-right`,[a(`line`,[d(`right`,{width:`28px`})])]),d(`dashed`,[a(`line`,`
 background-color: #0000;
 height: 0px;
 width: 100%;
 border-style: dashed;
 border-width: 1px 0 0;
 `)]),d(`vertical`,`
 display: inline-block;
 height: 1em;
 margin: 0 8px;
 vertical-align: middle;
 width: 1px;
 `),a(`line`,`
 border: none;
 transition: background-color .3s var(--n-bezier), border-color .3s var(--n-bezier);
 height: 1px;
 width: 100%;
 margin: 0;
 `),i(`dashed`,[a(`line`,{backgroundColor:`var(--n-color)`})]),d(`dashed`,[a(`line`,{borderColor:`var(--n-color)`})]),d(`vertical`,{backgroundColor:`var(--n-color)`})]),h=e({name:`Divider`,props:Object.assign(Object.assign({},l.props),{titlePlacement:{type:String,default:`center`},dashed:Boolean,vertical:Boolean}),setup(e){let{mergedClsPrefixRef:t,inlineThemeDisabled:n}=s(e),i=l(`Divider`,`-divider`,m,p,e,t),a=r(()=>{let{common:{cubicBezierEaseInOut:e},self:{color:t,textColor:n,fontWeight:r}}=i.value;return{"--n-bezier":e,"--n-color":t,"--n-text-color":n,"--n-font-weight":r}}),c=n?o(`divider`,void 0,a,e):void 0;return{mergedClsPrefix:t,cssVars:n?void 0:a,themeClass:c?.themeClass,onRender:c?.onRender}},render(){var e;let{$slots:r,titlePlacement:i,vertical:a,dashed:o,cssVars:s,mergedClsPrefix:c}=this;return(e=this.onRender)==null||e.call(this),t(`div`,{role:`separator`,class:[`${c}-divider`,this.themeClass,{[`${c}-divider--vertical`]:a,[`${c}-divider--no-title`]:!r.default,[`${c}-divider--dashed`]:o,[`${c}-divider--title-position-${i}`]:r.default&&i}],style:s},a?null:t(`div`,{class:`${c}-divider__line ${c}-divider__line--left`}),!a&&r.default?t(n,null,t(`div`,{class:`${c}-divider__title`},this.$slots),t(`div`,{class:`${c}-divider__line ${c}-divider__line--right`})):null)}});export{h as t};